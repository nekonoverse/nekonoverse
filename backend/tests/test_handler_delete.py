from tests.conftest import make_note, make_remote_actor


async def test_handle_delete_note(db, mock_valkey):
    from app.activitypub.handlers.delete import handle_delete
    remote = await make_remote_actor(db, username="del", domain="del.example")
    note = await make_note(db, remote, content="To be deleted", local=False)
    activity = {
        "type": "Delete",
        "actor": remote.ap_id,
        "object": {"type": "Tombstone", "id": note.ap_id},
    }
    await handle_delete(db, activity)
    await db.refresh(note)
    assert note.deleted_at is not None


async def test_handle_delete_string_object(db, mock_valkey):
    from app.activitypub.handlers.delete import handle_delete
    remote = await make_remote_actor(db, username="dels", domain="dels.example")
    note = await make_note(db, remote, content="Delete me", local=False)
    activity = {
        "type": "Delete",
        "actor": remote.ap_id,
        "object": note.ap_id,
    }
    await handle_delete(db, activity)
    await db.refresh(note)
    assert note.deleted_at is not None


async def test_handle_delete_wrong_owner(db, mock_valkey):
    from app.activitypub.handlers.delete import handle_delete
    owner = await make_remote_actor(db, username="owner", domain="own.example")
    other = await make_remote_actor(db, username="other", domain="oth.example")
    note = await make_note(db, owner, content="Not yours", local=False)
    activity = {
        "type": "Delete",
        "actor": other.ap_id,
        "object": note.ap_id,
    }
    await handle_delete(db, activity)
    await db.refresh(note)
    assert note.deleted_at is None  # Should not delete


async def test_handle_delete_nonexistent_note(db, mock_valkey):
    from app.activitypub.handlers.delete import handle_delete
    remote = await make_remote_actor(db, username="dne", domain="dne.example")
    activity = {
        "type": "Delete",
        "actor": remote.ap_id,
        "object": "http://localhost/notes/nonexistent",
    }
    await handle_delete(db, activity)  # Should not raise
