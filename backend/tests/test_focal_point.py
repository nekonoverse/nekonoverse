"""Tests for focal point support on media attachments."""

import io
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_note, make_remote_actor


# Minimal valid 1x1 PNG for upload tests
TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
    b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
    b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture
def mock_s3():
    """Mock S3 upload so we don't need real storage."""
    with (
        patch("app.services.drive_service.upload_file", new_callable=AsyncMock) as upload,
        patch("app.services.drive_service.get_public_url", return_value="http://test/media/test.png"),
    ):
        upload.return_value = "etag123"
        yield upload


async def test_upload_with_focus(authed_client, mock_s3):
    """Upload media with focus parameter returns meta.focus."""
    resp = await authed_client.post(
        "/api/v1/media",
        files={"file": ("test.png", TINY_PNG, "image/png")},
        data={"focus": "0.3,-0.2"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["meta"] is not None
    assert data["meta"]["focus"]["x"] == pytest.approx(0.3, abs=0.01)
    assert data["meta"]["focus"]["y"] == pytest.approx(-0.2, abs=0.01)


async def test_upload_without_focus_no_detect(authed_client, mock_s3):
    """Upload without focus and no FACE_DETECT_URL skips detection."""
    resp = await authed_client.post(
        "/api/v1/media",
        files={"file": ("test.png", TINY_PNG, "image/png")},
    )
    assert resp.status_code == 200
    data = resp.json()
    # No focus set — meta may have original dimensions but no focus
    if data["meta"]:
        assert "focus" not in data["meta"]


async def test_put_update_focal_point(authed_client, mock_s3):
    """PUT /api/v1/media/:id updates focal point."""
    # Upload first
    resp = await authed_client.post(
        "/api/v1/media",
        files={"file": ("test.png", TINY_PNG, "image/png")},
    )
    assert resp.status_code == 200
    media_id = resp.json()["id"]

    # Update focal point
    resp2 = await authed_client.put(
        f"/api/v1/media/{media_id}",
        data={"focus": "-0.5,0.7"},
    )
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["meta"]["focus"]["x"] == pytest.approx(-0.5, abs=0.01)
    assert data["meta"]["focus"]["y"] == pytest.approx(0.7, abs=0.01)


async def test_put_update_description(authed_client, mock_s3):
    """PUT /api/v1/media/:id updates description."""
    resp = await authed_client.post(
        "/api/v1/media",
        files={"file": ("test.png", TINY_PNG, "image/png")},
    )
    media_id = resp.json()["id"]

    resp2 = await authed_client.put(
        f"/api/v1/media/{media_id}",
        data={"description": "A cat photo"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["description"] == "A cat photo"


async def test_put_other_user_returns_404(authed_client, mock_s3, db, test_user_b):
    """PUT /api/v1/media/:id by non-owner returns 404 (not 403) to prevent enumeration."""
    # Upload as test_user (via authed_client)
    resp = await authed_client.post(
        "/api/v1/media",
        files={"file": ("test.png", TINY_PNG, "image/png")},
    )
    media_id = resp.json()["id"]

    # Switch session to test_user_b
    from unittest.mock import AsyncMock
    authed_client._transport.app.dependency_overrides.clear()

    from app.dependencies import get_current_user, get_db

    async def override_get_db():
        yield db

    async def override_get_user_b():
        return test_user_b

    authed_client._transport.app.dependency_overrides[get_db] = override_get_db
    authed_client._transport.app.dependency_overrides[get_current_user] = override_get_user_b

    resp2 = await authed_client.put(
        f"/api/v1/media/{media_id}",
        data={"focus": "0.0,0.0"},
    )
    assert resp2.status_code == 404


async def test_focal_point_clamped(authed_client, mock_s3):
    """Focal point values are clamped to [-1, 1]."""
    resp = await authed_client.post(
        "/api/v1/media",
        files={"file": ("test.png", TINY_PNG, "image/png")},
        data={"focus": "5.0,-3.0"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["meta"]["focus"]["x"] == pytest.approx(1.0, abs=0.01)
    assert data["meta"]["focus"]["y"] == pytest.approx(-1.0, abs=0.01)


async def test_invalid_focus_format(authed_client, mock_s3):
    """Invalid focus format is silently ignored."""
    resp = await authed_client.post(
        "/api/v1/media",
        files={"file": ("test.png", TINY_PNG, "image/png")},
        data={"focus": "invalid"},
    )
    assert resp.status_code == 200


async def test_auto_detect_no_service(db, test_user, mock_s3):
    """auto_detect_focal_point does nothing when FACE_DETECT_URL is not set."""
    from app.services.drive_service import auto_detect_focal_point, upload_drive_file

    drive_file = await upload_drive_file(
        db=db, owner=test_user, data=TINY_PNG,
        filename="test.png", mime_type="image/png",
    )
    with patch("app.services.drive_service.settings") as mock_settings:
        mock_settings.face_detect_url = None
        await auto_detect_focal_point(db, drive_file)
    assert drive_file.focal_x is None
    assert drive_file.focal_y is None


async def test_auto_detect_service_down(db, test_user, mock_s3):
    """auto_detect_focal_point silently fails when service is unreachable."""
    import httpx

    from app.services.drive_service import auto_detect_focal_point, upload_drive_file

    drive_file = await upload_drive_file(
        db=db, owner=test_user, data=TINY_PNG,
        filename="test.png", mime_type="image/png",
    )
    with (
        patch("app.services.drive_service.settings") as mock_settings,
        patch("app.storage.download_file", new_callable=AsyncMock, return_value=TINY_PNG),
        patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("connection refused")),
    ):
        mock_settings.face_detect_url = "http://gpu-host:8001/object-detection"
        await auto_detect_focal_point(db, drive_file)
    # Should not crash, focal point stays None
    assert drive_file.focal_x is None


async def test_ap_renderer_focal_point(db, test_user):
    """AP renderer includes focalPoint on attachments with focal point."""
    from app.activitypub.renderer import render_note
    from app.models.drive_file import DriveFile
    from app.models.note_attachment import NoteAttachment

    note = await make_note(db, test_user.actor)

    # Create a drive file with focal point
    drive_file = DriveFile(
        id=uuid.uuid4(),
        owner_id=test_user.id,
        s3_key="test/focal.png",
        filename="focal.png",
        mime_type="image/png",
        size_bytes=100,
        width=800,
        height=600,
        focal_x=0.3,
        focal_y=-0.2,
    )
    db.add(drive_file)
    await db.flush()

    att = NoteAttachment(
        note_id=note.id,
        drive_file_id=drive_file.id,
        position=0,
    )
    db.add(att)
    await db.flush()
    await db.refresh(note, ["attachments"])

    result = render_note(note)
    assert "attachment" in result
    assert result["attachment"][0]["focalPoint"] == [0.3, -0.2]


async def test_ap_create_handler_focal_point(db):
    """Create handler parses focalPoint from incoming AP attachments."""
    from app.activitypub.handlers.create import handle_create

    remote_actor = await make_remote_actor(db)

    activity = {
        "type": "Create",
        "actor": remote_actor.ap_id,
        "object": {
            "type": "Note",
            "id": f"http://remote.example/notes/{uuid.uuid4()}",
            "attributedTo": remote_actor.ap_id,
            "content": "<p>Test focal</p>",
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [],
            "attachment": [
                {
                    "type": "Document",
                    "mediaType": "image/jpeg",
                    "url": "http://remote.example/media/photo.jpg",
                    "name": "A photo",
                    "width": 1920,
                    "height": 1080,
                    "focalPoint": [0.5, -0.3],
                }
            ],
        },
    }

    await handle_create(db, activity)

    # Find the created note's attachment
    from sqlalchemy import select

    from app.models.note import Note
    from app.models.note_attachment import NoteAttachment

    note_result = await db.execute(
        select(Note).where(Note.actor_id == remote_actor.id)
    )
    note = note_result.scalar_one()

    att_result = await db.execute(
        select(NoteAttachment).where(NoteAttachment.note_id == note.id)
    )
    att = att_result.scalar_one()

    assert att.remote_focal_x == pytest.approx(0.5, abs=0.01)
    assert att.remote_focal_y == pytest.approx(-0.3, abs=0.01)


async def test_upload_with_nan_focus_ignored(authed_client, mock_s3):
    """NaN focus values are silently ignored."""
    resp = await authed_client.post(
        "/api/v1/media",
        files={"file": ("test.png", TINY_PNG, "image/png")},
        data={"focus": "nan,nan"},
    )
    assert resp.status_code == 200
    data = resp.json()
    if data["meta"]:
        assert "focus" not in data["meta"]


async def test_upload_with_inf_focus_ignored(authed_client, mock_s3):
    """Infinity focus values are silently ignored."""
    resp = await authed_client.post(
        "/api/v1/media",
        files={"file": ("test.png", TINY_PNG, "image/png")},
        data={"focus": "inf,-inf"},
    )
    assert resp.status_code == 200
    data = resp.json()
    if data["meta"]:
        assert "focus" not in data["meta"]


async def test_put_nonexistent_media_returns_404(authed_client, mock_s3):
    """PUT /api/v1/media/:id with non-existent ID returns 404."""
    fake_id = uuid.uuid4()
    resp = await authed_client.put(
        f"/api/v1/media/{fake_id}",
        data={"focus": "0.0,0.0"},
    )
    assert resp.status_code == 404


async def test_put_unauthenticated_returns_401(app_client, mock_s3):
    """PUT /api/v1/media/:id without auth returns 401."""
    fake_id = uuid.uuid4()
    resp = await app_client.put(
        f"/api/v1/media/{fake_id}",
        data={"focus": "0.0,0.0"},
    )
    assert resp.status_code == 401


async def test_auto_detect_happy_path(db, test_user, mock_s3):
    """auto_detect_focal_point successfully sets focal point from face detection."""
    from app.services.drive_service import auto_detect_focal_point, upload_drive_file

    drive_file = await upload_drive_file(
        db=db, owner=test_user, data=TINY_PNG,
        filename="test.png", mime_type="image/png",
    )
    # Fake dimensions for coordinate calculation
    drive_file.width = 100
    drive_file.height = 100
    await db.commit()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = [
        {"label": "face", "score": 0.95, "box": {"xmin": 30, "ymin": 20, "xmax": 70, "ymax": 60}}
    ]

    mock_post = AsyncMock(return_value=mock_response)
    with (
        patch("app.services.drive_service.settings") as mock_settings,
        patch("app.storage.download_file", new_callable=AsyncMock, return_value=TINY_PNG),
        patch("httpx.AsyncClient.post", mock_post),
    ):
        mock_settings.face_detect_url = "http://gpu-host:8001/object-detection"
        await auto_detect_focal_point(db, drive_file)

    # Center of box (50, 40) on 100x100 image → focal_x=0.0, focal_y=0.2
    assert drive_file.focal_x == pytest.approx(0.0, abs=0.01)
    assert drive_file.focal_y == pytest.approx(0.2, abs=0.01)


async def test_auto_detect_skips_when_focal_set(db, test_user, mock_s3):
    """auto_detect_focal_point skips when focal point is already set."""
    from app.services.drive_service import auto_detect_focal_point, upload_drive_file

    drive_file = await upload_drive_file(
        db=db, owner=test_user, data=TINY_PNG,
        filename="test.png", mime_type="image/png",
    )
    drive_file.focal_x = 0.5
    drive_file.focal_y = -0.3
    await db.commit()

    with patch("app.services.drive_service.settings") as mock_settings:
        mock_settings.face_detect_url = "http://gpu-host:8001/object-detection"
        await auto_detect_focal_point(db, drive_file)

    # Should remain unchanged
    assert drive_file.focal_x == pytest.approx(0.5, abs=0.01)
    assert drive_file.focal_y == pytest.approx(-0.3, abs=0.01)


async def test_auto_detect_invalid_url_scheme(db, test_user, mock_s3):
    """auto_detect_focal_point rejects non-http(s) URL schemes."""
    from app.services.drive_service import auto_detect_focal_point, upload_drive_file

    drive_file = await upload_drive_file(
        db=db, owner=test_user, data=TINY_PNG,
        filename="test.png", mime_type="image/png",
    )

    with patch("app.services.drive_service.settings") as mock_settings:
        mock_settings.face_detect_url = "file:///etc/passwd"
        await auto_detect_focal_point(db, drive_file)

    assert drive_file.focal_x is None


async def test_ap_create_nan_focal_point(db):
    """Create handler ignores NaN focalPoint values from AP."""
    from app.activitypub.handlers.create import handle_create

    remote_actor = await make_remote_actor(db)

    activity = {
        "type": "Create",
        "actor": remote_actor.ap_id,
        "object": {
            "type": "Note",
            "id": f"http://remote.example/notes/{uuid.uuid4()}",
            "attributedTo": remote_actor.ap_id,
            "content": "<p>NaN test</p>",
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [],
            "attachment": [
                {
                    "type": "Document",
                    "mediaType": "image/jpeg",
                    "url": "http://remote.example/media/nan.jpg",
                    "focalPoint": [float("nan"), float("nan")],
                }
            ],
        },
    }

    await handle_create(db, activity)

    from sqlalchemy import select
    from app.models.note import Note
    from app.models.note_attachment import NoteAttachment

    note_result = await db.execute(
        select(Note).where(Note.actor_id == remote_actor.id)
    )
    note = note_result.scalar_one()

    att_result = await db.execute(
        select(NoteAttachment).where(NoteAttachment.note_id == note.id)
    )
    att = att_result.scalar_one()
    assert att.remote_focal_x is None
    assert att.remote_focal_y is None


async def test_ap_create_malformed_focal_point(db):
    """Create handler ignores malformed focalPoint (non-list, single element, etc)."""
    from app.activitypub.handlers.create import handle_create

    remote_actor = await make_remote_actor(db)

    # Test with string instead of list
    activity = {
        "type": "Create",
        "actor": remote_actor.ap_id,
        "object": {
            "type": "Note",
            "id": f"http://remote.example/notes/{uuid.uuid4()}",
            "attributedTo": remote_actor.ap_id,
            "content": "<p>Malformed focal</p>",
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [],
            "attachment": [
                {
                    "type": "Document",
                    "mediaType": "image/jpeg",
                    "url": "http://remote.example/media/bad.jpg",
                    "focalPoint": "not-a-list",
                }
            ],
        },
    }

    await handle_create(db, activity)

    from sqlalchemy import select
    from app.models.note import Note
    from app.models.note_attachment import NoteAttachment

    note_result = await db.execute(
        select(Note).where(Note.actor_id == remote_actor.id)
    )
    notes = note_result.scalars().all()
    latest = notes[-1]  # Get the one we just created

    att_result = await db.execute(
        select(NoteAttachment).where(NoteAttachment.note_id == latest.id)
    )
    att = att_result.scalar_one()
    assert att.remote_focal_x is None
    assert att.remote_focal_y is None
