"""Tests for Update handler."""

from tests.conftest import make_note, make_remote_actor


async def test_update_actor(db, mock_valkey):
    from app.activitypub.handlers.update import handle_update

    remote_actor = await make_remote_actor(db, username="updatable", domain="upd.example")
    await db.commit()

    activity = {
        "type": "Update",
        "actor": remote_actor.ap_id,
        "object": {
            "id": remote_actor.ap_id,
            "type": "Person",
            "preferredUsername": "updatable",
            "name": "Updated Name",
            "summary": "New bio",
            "inbox": remote_actor.inbox_url,
            "publicKey": {
                "id": f"{remote_actor.ap_id}#main-key",
                "publicKeyPem": remote_actor.public_key_pem,
            },
            "isCat": True,
        },
    }

    await handle_update(db, activity)

    await db.refresh(remote_actor)
    assert remote_actor.display_name == "Updated Name"
    assert remote_actor.summary == "New bio"
    assert remote_actor.is_cat is True


async def test_update_note(db, mock_valkey):
    from app.activitypub.handlers.update import handle_update

    remote_actor = await make_remote_actor(db, username="noteeditor", domain="edit.example")
    note = await make_note(db, remote_actor, content="<p>Original</p>", local=False)
    await db.commit()

    activity = {
        "type": "Update",
        "actor": remote_actor.ap_id,
        "object": {
            "id": note.ap_id,
            "type": "Note",
            "content": "<p>Edited content</p>",
            "sensitive": True,
            "summary": "Content warning",
        },
    }

    await handle_update(db, activity)

    await db.refresh(note)
    assert "Edited content" in note.content
    assert note.sensitive is True
    assert note.spoiler_text == "Content warning"
    assert note.updated_at is not None


async def test_update_actor_mismatch(db, mock_valkey):
    """Update should be rejected if actor doesn't match object.id."""
    from app.activitypub.handlers.update import handle_update

    remote_actor = await make_remote_actor(db, username="mismatch", domain="mm.example")
    await db.commit()

    activity = {
        "type": "Update",
        "actor": remote_actor.ap_id,
        "object": {
            "id": "http://other.example/users/someone",
            "type": "Person",
            "preferredUsername": "someone",
            "name": "Hacker",
        },
    }

    await handle_update(db, activity)

    # Actor should not be modified
    await db.refresh(remote_actor)
    assert remote_actor.display_name != "Hacker"


async def test_update_note_not_owned(db, mock_valkey):
    """Update should be rejected if actor doesn't own the note."""
    from app.activitypub.handlers.update import handle_update

    actor_a = await make_remote_actor(db, username="owner", domain="own.example")
    actor_b = await make_remote_actor(db, username="attacker", domain="atk.example")
    note = await make_note(db, actor_a, content="<p>My note</p>", local=False)
    await db.commit()

    activity = {
        "type": "Update",
        "actor": actor_b.ap_id,
        "object": {
            "id": note.ap_id,
            "type": "Note",
            "content": "<p>Hacked</p>",
        },
    }

    await handle_update(db, activity)

    await db.refresh(note)
    assert "Hacked" not in note.content
