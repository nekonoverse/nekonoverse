from tests.conftest import make_remote_actor


async def test_handle_create_note(db, mock_valkey):
    from app.activitypub.handlers.create import handle_create
    remote = await make_remote_actor(db, username="sender", domain="sender.example")
    activity = {
        "type": "Create",
        "actor": remote.ap_id,
        "object": {
            "type": "Note",
            "id": "http://sender.example/notes/1",
            "attributedTo": remote.ap_id,
            "content": "<p>Hello from remote</p>",
            "published": "2025-06-01T00:00:00Z",
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [],
        }
    }
    await handle_create(db, activity)
    from app.services.note_service import get_note_by_ap_id
    note = await get_note_by_ap_id(db, "http://sender.example/notes/1")
    assert note is not None
    assert note.local is False


async def test_handle_create_note_duplicate_skipped(db, mock_valkey):
    from app.activitypub.handlers.create import handle_create
    remote = await make_remote_actor(db, username="dup", domain="dup.example")
    activity = {
        "type": "Create",
        "actor": remote.ap_id,
        "object": {
            "type": "Note",
            "id": "http://dup.example/notes/dup1",
            "attributedTo": remote.ap_id,
            "content": "<p>First</p>",
            "published": "2025-06-01T00:00:00Z",
            "to": [], "cc": [],
        }
    }
    await handle_create(db, activity)
    await handle_create(db, activity)  # Should not raise
    from sqlalchemy import select, func
    from app.models.note import Note
    count = await db.scalar(select(func.count()).where(Note.ap_id == "http://dup.example/notes/dup1"))
    assert count == 1


async def test_handle_create_note_no_id_skipped(db, mock_valkey):
    from app.activitypub.handlers.create import handle_create
    activity = {
        "type": "Create",
        "actor": "http://example.com/users/x",
        "object": {
            "type": "Note",
            "content": "<p>No ID</p>",
            "published": "2025-06-01T00:00:00Z",
            "to": [], "cc": [],
        }
    }
    await handle_create(db, activity)  # Should not raise


async def test_handle_create_public_visibility(db, mock_valkey):
    from app.activitypub.handlers.create import handle_create
    from app.services.note_service import get_note_by_ap_id
    remote = await make_remote_actor(db, username="pub", domain="pub.example")
    activity = {
        "type": "Create",
        "actor": remote.ap_id,
        "object": {
            "type": "Note",
            "id": "http://pub.example/notes/pub1",
            "attributedTo": remote.ap_id,
            "content": "<p>Public</p>",
            "published": "2025-06-01T00:00:00Z",
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [f"{remote.ap_id}/followers"],
        }
    }
    await handle_create(db, activity)
    note = await get_note_by_ap_id(db, "http://pub.example/notes/pub1")
    assert note.visibility == "public"


async def test_handle_create_unlisted_visibility(db, mock_valkey):
    from app.activitypub.handlers.create import handle_create
    from app.services.note_service import get_note_by_ap_id
    remote = await make_remote_actor(db, username="unl", domain="unl.example")
    activity = {
        "type": "Create",
        "actor": remote.ap_id,
        "object": {
            "type": "Note",
            "id": "http://unl.example/notes/unl1",
            "attributedTo": remote.ap_id,
            "content": "<p>Unlisted</p>",
            "published": "2025-06-01T00:00:00Z",
            "to": [f"{remote.ap_id}/followers"],
            "cc": ["https://www.w3.org/ns/activitystreams#Public"],
        }
    }
    await handle_create(db, activity)
    note = await get_note_by_ap_id(db, "http://unl.example/notes/unl1")
    assert note.visibility == "unlisted"


async def test_handle_create_string_object_skipped(db, mock_valkey):
    from app.activitypub.handlers.create import handle_create
    activity = {
        "type": "Create",
        "actor": "http://example.com/users/x",
        "object": "http://example.com/notes/string-ref"
    }
    await handle_create(db, activity)  # Should not raise


async def test_handle_create_with_source(db, mock_valkey):
    from app.activitypub.handlers.create import handle_create
    from app.services.note_service import get_note_by_ap_id
    remote = await make_remote_actor(db, username="src", domain="src.example")
    activity = {
        "type": "Create",
        "actor": remote.ap_id,
        "object": {
            "type": "Note",
            "id": "http://src.example/notes/src1",
            "attributedTo": remote.ap_id,
            "content": "<p>With source</p>",
            "source": {"content": "With source", "mediaType": "text/plain"},
            "published": "2025-06-01T00:00:00Z",
            "to": [], "cc": [],
        }
    }
    await handle_create(db, activity)
    note = await get_note_by_ap_id(db, "http://src.example/notes/src1")
    assert note.source == "With source"


async def test_handle_create_sanitizes_content(db, mock_valkey):
    from app.activitypub.handlers.create import handle_create
    from app.services.note_service import get_note_by_ap_id
    remote = await make_remote_actor(db, username="san", domain="san.example")
    activity = {
        "type": "Create",
        "actor": remote.ap_id,
        "object": {
            "type": "Note",
            "id": "http://san.example/notes/san1",
            "attributedTo": remote.ap_id,
            "content": '<p>Hello</p><script>alert("xss")</script>',
            "published": "2025-06-01T00:00:00Z",
            "to": [], "cc": [],
        }
    }
    await handle_create(db, activity)
    note = await get_note_by_ap_id(db, "http://san.example/notes/san1")
    assert "<script>" not in note.content
