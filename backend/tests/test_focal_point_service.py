"""Tests for background focal point detection service."""

import uuid
from unittest.mock import AsyncMock, patch

from tests.conftest import make_note, make_remote_actor


async def _make_attachment(db, note, *, mime="image/jpeg", url="https://r.example/img.jpg",
                           focal_x=None, focal_y=None, width=800, height=600):
    from app.models.note_attachment import NoteAttachment
    att = NoteAttachment(
        note_id=note.id,
        position=0,
        remote_url=url,
        remote_mime_type=mime,
        remote_width=width,
        remote_height=height,
        remote_focal_x=focal_x,
        remote_focal_y=focal_y,
    )
    db.add(att)
    await db.flush()
    return att


async def test_detect_single_success(db, mock_valkey):
    """Face detection updates remote_focal_x/y on attachment."""
    from app.services.focal_point_service import _detect_single

    actor = await make_remote_actor(db, username="fp_ok", domain="ok.example")
    note = await make_note(db, actor, content="With image", local=False)
    att = await _make_attachment(db, note)

    with patch(
        "app.services.focal_point_service._download_image",
        new=AsyncMock(return_value=b"\xff\xd8" + b"\x00" * 100),
    ), patch(
        "app.services.focal_point_service._call_face_detect",
        new=AsyncMock(return_value=(0.25, -0.1)),
    ):
        result = await _detect_single(att)

    assert result is True
    assert att.remote_focal_x == 0.25
    assert att.remote_focal_y == -0.1


async def test_detect_single_skips_non_image(db, mock_valkey):
    from app.services.focal_point_service import _detect_single

    actor = await make_remote_actor(db, username="fp_vid", domain="vid.example")
    note = await make_note(db, actor, content="Video", local=False)
    att = await _make_attachment(db, note, mime="video/mp4")

    result = await _detect_single(att)
    assert result is False


async def test_detect_single_skips_existing_focal(db, mock_valkey):
    from app.services.focal_point_service import _detect_single

    actor = await make_remote_actor(db, username="fp_exist", domain="exist.example")
    note = await make_note(db, actor, content="Has focal", local=False)
    att = await _make_attachment(db, note, focal_x=0.5, focal_y=-0.3)

    result = await _detect_single(att)
    assert result is False


async def test_detect_single_download_failure(db, mock_valkey):
    from app.services.focal_point_service import _detect_single

    actor = await make_remote_actor(db, username="fp_dl", domain="dl.example")
    note = await make_note(db, actor, content="DL fail", local=False)
    att = await _make_attachment(db, note)

    with patch(
        "app.services.focal_point_service._download_image",
        new=AsyncMock(return_value=None),
    ):
        result = await _detect_single(att)

    assert result is False
    assert att.remote_focal_x is None


async def test_detect_single_service_unavailable(db, mock_valkey):
    from app.services.focal_point_service import _detect_single

    actor = await make_remote_actor(db, username="fp_svc", domain="svc.example")
    note = await make_note(db, actor, content="Svc down", local=False)
    att = await _make_attachment(db, note)

    with patch(
        "app.services.focal_point_service._download_image",
        new=AsyncMock(return_value=b"fake-image"),
    ), patch(
        "app.services.focal_point_service._call_face_detect",
        new=AsyncMock(return_value=None),
    ):
        result = await _detect_single(att)

    assert result is False
    assert att.remote_focal_x is None


async def test_detect_remote_focal_points_integration(db, mock_valkey):
    """Full flow: detect, update DB, and publish streaming event."""
    from contextlib import asynccontextmanager
    from app.services.focal_point_service import detect_remote_focal_points

    actor = await make_remote_actor(db, username="fp_full", domain="full.example")
    note = await make_note(db, actor, content="Full test", local=False)
    att = await _make_attachment(db, note)
    await db.flush()

    # Mock async_session to return the test's db session so data is visible
    @asynccontextmanager
    async def fake_session():
        yield db

    with patch("app.services.focal_point_service.settings") as mock_settings, \
         patch("app.database.async_session", fake_session), \
         patch(
             "app.services.focal_point_service._download_image",
             new=AsyncMock(return_value=b"img"),
         ), \
         patch(
             "app.services.focal_point_service._call_face_detect",
             new=AsyncMock(return_value=(0.1, 0.2)),
         ), \
         patch(
             "app.services.focal_point_service._publish_update",
             new=AsyncMock(),
         ) as mock_publish:
        mock_settings.face_detect_url = "http://localhost:9999"
        mock_settings.skip_ssl_verify = False
        await detect_remote_focal_points(note.id, [att.id])

    mock_publish.assert_called_once_with(note.id)


async def test_detect_skips_no_url(db, mock_valkey):
    """Attachment without remote_url is skipped."""
    from app.services.focal_point_service import _detect_single
    from app.models.note_attachment import NoteAttachment

    actor = await make_remote_actor(db, username="fp_nourl", domain="nourl.example")
    note = await make_note(db, actor, content="No URL", local=False)
    att = NoteAttachment(
        note_id=note.id,
        position=0,
        remote_url=None,
        remote_mime_type="image/jpeg",
    )
    db.add(att)
    await db.flush()

    result = await _detect_single(att)
    assert result is False
