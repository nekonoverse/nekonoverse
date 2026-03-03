from datetime import datetime, timezone

import pytest

from app.models.reaction import Reaction
from tests.conftest import make_note, make_remote_actor


async def test_create_note_public(db, test_user, mock_valkey):
    from app.services.note_service import create_note
    note = await create_note(db, test_user, "Hello world", visibility="public")
    assert note.visibility == "public"
    assert "https://www.w3.org/ns/activitystreams#Public" in note.to
    assert note.local is True
    assert "<p>" in note.content


async def test_create_note_unlisted(db, test_user, mock_valkey):
    from app.services.note_service import create_note
    note = await create_note(db, test_user, "Unlisted", visibility="unlisted")
    assert "https://www.w3.org/ns/activitystreams#Public" in note.cc


async def test_create_note_followers(db, test_user, mock_valkey):
    from app.services.note_service import create_note
    note = await create_note(db, test_user, "Followers only", visibility="followers")
    assert note.to[0].endswith("/followers")
    assert "https://www.w3.org/ns/activitystreams#Public" not in note.to
    assert "https://www.w3.org/ns/activitystreams#Public" not in note.cc


async def test_create_note_stores_source(db, test_user, mock_valkey):
    from app.services.note_service import create_note
    note = await create_note(db, test_user, "raw text")
    assert note.source == "raw text"


async def test_create_note_sensitive(db, test_user, mock_valkey):
    from app.services.note_service import create_note
    note = await create_note(db, test_user, "nsfw", sensitive=True, spoiler_text="CW")
    assert note.sensitive is True
    assert note.spoiler_text == "CW"


async def test_get_note_by_id(db, test_user, mock_valkey):
    from app.services.note_service import create_note, get_note_by_id
    note = await create_note(db, test_user, "test")
    fetched = await get_note_by_id(db, note.id)
    assert fetched is not None
    assert fetched.id == note.id


async def test_get_note_by_id_deleted(db, test_user, mock_valkey):
    from app.services.note_service import create_note, get_note_by_id
    note = await create_note(db, test_user, "deleted")
    note.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    fetched = await get_note_by_id(db, note.id)
    assert fetched is None


async def test_get_public_timeline(db, test_user, mock_valkey):
    from app.services.note_service import create_note, get_public_timeline
    await create_note(db, test_user, "note1")
    await create_note(db, test_user, "note2")
    notes = await get_public_timeline(db, limit=10)
    assert len(notes) >= 2


async def test_get_public_timeline_local_only(db, test_user, mock_valkey):
    from app.services.note_service import create_note, get_public_timeline
    await create_note(db, test_user, "local note")
    remote_actor = await make_remote_actor(db)
    await make_note(db, remote_actor, content="remote", local=False)
    local_notes = await get_public_timeline(db, limit=50, local_only=True)
    assert all(n.local for n in local_notes)


async def test_get_public_timeline_pagination(db, test_user, mock_valkey):
    from app.services.note_service import create_note, get_public_timeline
    notes = []
    for i in range(5):
        n = await create_note(db, test_user, f"note {i}")
        notes.append(n)
    page = await get_public_timeline(db, limit=2, max_id=notes[2].id)
    assert len(page) <= 2


async def test_get_reaction_summary(db, test_user, mock_valkey):
    from app.services.note_service import create_note, get_reaction_summary
    note = await create_note(db, test_user, "react me")
    r = Reaction(actor_id=test_user.actor_id, note_id=note.id, emoji="\U0001f600")
    db.add(r)
    await db.flush()
    summary = await get_reaction_summary(db, note.id, current_actor_id=test_user.actor_id)
    assert len(summary) == 1
    assert summary[0]["emoji"] == "\U0001f600"
    assert summary[0]["count"] == 1
    assert summary[0]["me"] is True


async def test_get_reaction_summary_me_false(db, test_user, test_user_b, mock_valkey):
    from app.services.note_service import create_note, get_reaction_summary
    note = await create_note(db, test_user, "react me")
    r = Reaction(actor_id=test_user.actor_id, note_id=note.id, emoji="\U0001f600")
    db.add(r)
    await db.flush()
    summary = await get_reaction_summary(db, note.id, current_actor_id=test_user_b.actor_id)
    assert summary[0]["me"] is False
