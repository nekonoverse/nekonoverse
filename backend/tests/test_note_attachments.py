"""Tests for media attachment federation (NoteAttachment model + AP rendering)."""

import uuid

from tests.conftest import make_note, make_remote_actor


async def make_drive_file(db, owner_id, *, filename="test.png", mime_type="image/png"):
    from app.models.drive_file import DriveFile
    df = DriveFile(
        owner_id=owner_id,
        s3_key=f"u/{owner_id}/{uuid.uuid4()}.png",
        filename=filename,
        mime_type=mime_type,
        size_bytes=1024,
        width=800,
        height=600,
        description="Test image",
        blurhash="UBL_:rOpGG-nt7t7RjWB~qxu%MRj",
    )
    db.add(df)
    await db.flush()
    return df


# --- NoteAttachment model tests ---


async def test_create_note_attachment(db, mock_valkey):
    """NoteAttachment can link a note to a drive file."""
    from app.models.note_attachment import NoteAttachment
    from app.services.user_service import create_user

    user = await create_user(db, "att_user", "att@test.com", "password1234")
    note = await make_note(db, user.actor, content="With attachment")
    df = await make_drive_file(db, user.id)

    att = NoteAttachment(
        note_id=note.id,
        drive_file_id=df.id,
        position=0,
    )
    db.add(att)
    await db.flush()

    assert att.id is not None
    assert att.note_id == note.id
    assert att.drive_file_id == df.id
    assert att.position == 0


async def test_remote_attachment_fields(db, mock_valkey):
    """NoteAttachment can store remote attachment data without a drive file."""
    from app.models.note_attachment import NoteAttachment

    remote_actor = await make_remote_actor(db, username="remote_att", domain="att.example")
    note = await make_note(db, remote_actor, content="Remote media", local=False)

    att = NoteAttachment(
        note_id=note.id,
        position=0,
        remote_url="https://att.example/media/image.jpg",
        remote_mime_type="image/jpeg",
        remote_name="image.jpg",
        remote_blurhash="UBLA",
        remote_width=1920,
        remote_height=1080,
        remote_description="A photo",
    )
    db.add(att)
    await db.flush()

    assert att.drive_file_id is None
    assert att.remote_url == "https://att.example/media/image.jpg"
    assert att.remote_width == 1920


# --- API: create status with media_ids ---


async def test_create_status_with_media(authed_client, test_user, db, mock_valkey):
    """Creating a note with media_ids attaches files to the note."""
    df = await make_drive_file(db, test_user.id)
    await db.flush()

    resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Photo post",
        "visibility": "public",
        "media_ids": [str(df.id)],
    })
    assert resp.status_code == 201
    data = resp.json()
    assert len(data["media_attachments"]) == 1
    att = data["media_attachments"][0]
    assert att["type"] == "image"
    assert att["description"] == "Test image"
    assert att["blurhash"] is not None


async def test_create_status_max_4_media_rejected(authed_client, test_user, db, mock_valkey):
    """Sending more than 4 media_ids is rejected by the schema."""
    files = [await make_drive_file(db, test_user.id, filename=f"img{i}.png") for i in range(5)]
    await db.flush()

    resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Too many photos",
        "visibility": "public",
        "media_ids": [str(f.id) for f in files],
    })
    assert resp.status_code == 422


async def test_create_status_invalid_media_id(authed_client, mock_valkey):
    """Non-existent media_id is silently ignored."""
    resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Bad media",
        "visibility": "public",
        "media_ids": [str(uuid.uuid4())],
    })
    assert resp.status_code == 201
    assert len(resp.json()["media_attachments"]) == 0


# --- AP renderer: attachments in Note ---


async def test_render_note_with_attachment(db, mock_valkey):
    """render_note() includes attachment array for notes with media."""
    from app.activitypub.renderer import render_note
    from app.models.note_attachment import NoteAttachment
    from app.services.user_service import create_user

    user = await create_user(db, "render_att", "ratt@test.com", "password1234")
    note = await make_note(db, user.actor, content="Rendering test")
    df = await make_drive_file(db, user.id)
    att = NoteAttachment(note_id=note.id, drive_file_id=df.id, position=0)
    db.add(att)
    await db.flush()

    # Reload note with relationships
    from app.services.note_service import get_note_by_id
    note = await get_note_by_id(db, note.id)

    rendered = render_note(note)
    assert "attachment" in rendered
    assert len(rendered["attachment"]) == 1
    doc = rendered["attachment"][0]
    assert doc["type"] == "Document"
    assert doc["mediaType"] == "image/png"
    assert "width" in doc
    assert "height" in doc


# --- Incoming Create with attachments ---


async def test_handle_create_with_attachments(db, mock_valkey):
    """Incoming Create(Note) with attachments saves NoteAttachment records."""
    from app.activitypub.handlers.create import handle_create

    remote_actor = await make_remote_actor(db, username="media_sender", domain="media.example")
    await db.commit()

    note_ap_id = "http://media.example/notes/with-media"
    activity = {
        "type": "Create",
        "actor": remote_actor.ap_id,
        "object": {
            "id": note_ap_id,
            "type": "Note",
            "attributedTo": remote_actor.ap_id,
            "content": "<p>Check this out</p>",
            "published": "2026-03-06T12:00:00Z",
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [],
            "attachment": [
                {
                    "type": "Document",
                    "mediaType": "image/jpeg",
                    "url": "https://media.example/files/photo.jpg",
                    "name": "A nice photo",
                    "width": 1200,
                    "height": 900,
                    "blurhash": "UBLA",
                },
                {
                    "type": "Image",
                    "mediaType": "image/png",
                    "url": "https://media.example/files/screenshot.png",
                    "name": "Screenshot",
                },
            ],
        },
    }

    await handle_create(db, activity)

    from app.services.note_service import get_note_by_ap_id
    note = await get_note_by_ap_id(db, note_ap_id)
    assert note is not None
    assert len(note.attachments) == 2
    assert note.attachments[0].remote_url == "https://media.example/files/photo.jpg"
    assert note.attachments[0].remote_width == 1200
    assert note.attachments[1].remote_mime_type == "image/png"


async def test_handle_create_attachment_limit(db, mock_valkey):
    """Incoming note with >4 attachments only saves the first 4."""
    from app.activitypub.handlers.create import handle_create

    remote_actor = await make_remote_actor(db, username="many_media", domain="manymedia.example")
    await db.commit()

    attachments = [
        {"type": "Document", "mediaType": "image/jpeg", "url": f"https://manymedia.example/f/{i}.jpg", "name": f"img{i}"}
        for i in range(6)
    ]

    activity = {
        "type": "Create",
        "actor": remote_actor.ap_id,
        "object": {
            "id": "http://manymedia.example/notes/toomany",
            "type": "Note",
            "attributedTo": remote_actor.ap_id,
            "content": "<p>Many attachments</p>",
            "published": "2026-03-06T12:00:00Z",
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [],
            "attachment": attachments,
        },
    }

    await handle_create(db, activity)

    from app.services.note_service import get_note_by_ap_id
    note = await get_note_by_ap_id(db, "http://manymedia.example/notes/toomany")
    assert len(note.attachments) == 4
