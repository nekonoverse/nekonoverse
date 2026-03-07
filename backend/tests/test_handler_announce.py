"""Tests for Announce (boost/renote) handler."""

from tests.conftest import make_note, make_remote_actor


async def test_handle_announce(db, mock_valkey):
    from app.activitypub.handlers.announce import handle_announce

    remote_actor = await make_remote_actor(db, username="booster", domain="remote.example")
    from sqlalchemy import select
    from app.models.actor import Actor
    result = await db.execute(select(Actor).where(Actor.domain.is_(None)).limit(1))
    local_actor = result.scalar_one_or_none()
    if not local_actor:
        # Create a local actor for making a note
        from tests.conftest import make_remote_actor as _mra
        # Use make_note with a minimal local actor setup
        from app.services.user_service import create_user
        user = await create_user(db, "announceuser", "announce@test.com", "password1234")
        local_actor = user.actor

    note = await make_note(db, local_actor, content="Original post")
    await db.commit()

    activity = {
        "id": "http://remote.example/activities/announce-1",
        "type": "Announce",
        "actor": remote_actor.ap_id,
        "object": note.ap_id,
        "to": ["https://www.w3.org/ns/activitystreams#Public"],
        "cc": [remote_actor.followers_url],
        "published": "2026-03-06T12:00:00Z",
    }

    await handle_announce(db, activity)

    # Verify renote was created
    from app.services.note_service import get_note_by_ap_id
    renote = await get_note_by_ap_id(db, "http://remote.example/activities/announce-1")
    assert renote is not None
    assert renote.renote_of_id == note.id
    assert renote.renote_of_ap_id == note.ap_id
    assert renote.visibility == "public"

    # Verify renotes_count incremented
    await db.refresh(note)
    assert note.renotes_count == 1


async def test_handle_announce_duplicate(db, mock_valkey):
    from app.activitypub.handlers.announce import handle_announce

    remote_actor = await make_remote_actor(db, username="dup_booster", domain="dup.example")
    from app.services.user_service import create_user
    user = await create_user(db, "dupannounce", "dupann@test.com", "password1234")
    note = await make_note(db, user.actor, content="Dup test")
    await db.commit()

    activity = {
        "id": "http://dup.example/activities/announce-dup",
        "type": "Announce",
        "actor": remote_actor.ap_id,
        "object": note.ap_id,
        "to": ["https://www.w3.org/ns/activitystreams#Public"],
        "cc": [],
    }

    await handle_announce(db, activity)
    await handle_announce(db, activity)  # duplicate

    # Should only have one renote
    from sqlalchemy import select, func
    from app.models.note import Note
    count_result = await db.execute(
        select(func.count()).select_from(Note).where(
            Note.renote_of_id == note.id,
            Note.deleted_at.is_(None),
        )
    )
    assert count_result.scalar() == 1


async def test_handle_announce_unknown_note(db, mock_valkey):
    """Announce of a note we don't have should still create the renote."""
    from app.activitypub.handlers.announce import handle_announce

    remote_actor = await make_remote_actor(db, username="unk_booster", domain="unk.example")
    await db.commit()

    activity = {
        "id": "http://unk.example/activities/announce-unk",
        "type": "Announce",
        "actor": remote_actor.ap_id,
        "object": "http://other.example/notes/unknown-note",
        "to": ["https://www.w3.org/ns/activitystreams#Public"],
        "cc": [],
    }

    await handle_announce(db, activity)

    from app.services.note_service import get_note_by_ap_id
    renote = await get_note_by_ap_id(db, "http://unk.example/activities/announce-unk")
    assert renote is not None
    assert renote.renote_of_id is None
    assert renote.renote_of_ap_id == "http://other.example/notes/unknown-note"
