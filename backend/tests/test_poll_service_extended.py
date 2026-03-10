"""Extended tests for poll_service — voting and poll data retrieval."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.poll_service import get_poll_data, vote_on_poll


async def _make_poll_note(db, actor, *, options=None, expires_at=None, multiple=False):
    """Create a note with poll data."""
    from app.models.note import Note

    note_id = uuid.uuid4()
    poll_options = options or [
        {"title": "Option A", "votes_count": 0},
        {"title": "Option B", "votes_count": 0},
    ]
    note = Note(
        id=note_id,
        ap_id=f"http://localhost/notes/{note_id}",
        actor_id=actor.id,
        content="<p>Poll question</p>",
        source="Poll question",
        visibility="public",
        local=True,
        to=["https://www.w3.org/ns/activitystreams#Public"],
        cc=[],
        is_poll=True,
        poll_options=poll_options,
        poll_expires_at=expires_at,
        poll_multiple=multiple,
    )
    db.add(note)
    await db.flush()
    return note


# ── vote_on_poll ─────────────────────────────────────────────────────────


async def test_vote_on_poll_success(db, mock_valkey, test_user, test_user_b):
    note = await _make_poll_note(db, test_user.actor)
    await vote_on_poll(db, test_user_b, note.id, [0])

    data = await get_poll_data(db, note.id, test_user_b.actor_id)
    assert data is not None
    assert data["voted"] is True
    assert 0 in data["own_votes"]
    assert data["options"][0]["votes_count"] == 1


async def test_vote_on_poll_not_found(db, mock_valkey, test_user):
    with pytest.raises(ValueError, match="Note not found"):
        await vote_on_poll(db, test_user, uuid.uuid4(), [0])


async def test_vote_on_non_poll_note(db, mock_valkey, test_user, test_user_b):
    from tests.conftest import make_note

    note = await make_note(db, test_user.actor, content="Not a poll")
    with pytest.raises(ValueError, match="Not a poll"):
        await vote_on_poll(db, test_user_b, note.id, [0])


async def test_vote_on_expired_poll(db, mock_valkey, test_user, test_user_b):
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    note = await _make_poll_note(db, test_user.actor, expires_at=past)
    with pytest.raises(ValueError, match="Poll has expired"):
        await vote_on_poll(db, test_user_b, note.id, [0])


async def test_vote_duplicate_raises(db, mock_valkey, test_user, test_user_b):
    note = await _make_poll_note(db, test_user.actor)
    await vote_on_poll(db, test_user_b, note.id, [0])
    with pytest.raises(ValueError, match="Already voted"):
        await vote_on_poll(db, test_user_b, note.id, [1])


async def test_vote_invalid_choice_index(db, mock_valkey, test_user, test_user_b):
    note = await _make_poll_note(db, test_user.actor)
    with pytest.raises(ValueError, match="Invalid choice index"):
        await vote_on_poll(db, test_user_b, note.id, [5])


async def test_vote_multiple_not_allowed(db, mock_valkey, test_user, test_user_b):
    note = await _make_poll_note(db, test_user.actor, multiple=False)
    with pytest.raises(ValueError, match="Multiple choices not allowed"):
        await vote_on_poll(db, test_user_b, note.id, [0, 1])


async def test_vote_multiple_allowed(db, mock_valkey, test_user, test_user_b):
    note = await _make_poll_note(db, test_user.actor, multiple=True)
    await vote_on_poll(db, test_user_b, note.id, [0, 1])
    data = await get_poll_data(db, note.id, test_user_b.actor_id)
    assert set(data["own_votes"]) == {0, 1}
    assert data["options"][0]["votes_count"] == 1
    assert data["options"][1]["votes_count"] == 1


# ── get_poll_data ────────────────────────────────────────────────────────


async def test_get_poll_data_returns_none_for_non_poll(db, mock_valkey, test_user):
    from tests.conftest import make_note

    note = await make_note(db, test_user.actor)
    result = await get_poll_data(db, note.id)
    assert result is None


async def test_get_poll_data_structure(db, mock_valkey, test_user):
    future = datetime.now(timezone.utc) + timedelta(hours=24)
    note = await _make_poll_note(db, test_user.actor, expires_at=future, multiple=True)
    data = await get_poll_data(db, note.id)
    assert data is not None
    assert data["id"] == str(note.id)
    assert data["expired"] is False
    assert data["multiple"] is True
    assert data["votes_count"] == 0
    assert data["voters_count"] == 0
    assert len(data["options"]) == 2
    assert data["voted"] is False
    assert data["own_votes"] == []


async def test_get_poll_data_expired(db, mock_valkey, test_user):
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    note = await _make_poll_note(db, test_user.actor, expires_at=past)
    data = await get_poll_data(db, note.id)
    assert data["expired"] is True


async def test_get_poll_data_with_voter(db, mock_valkey, test_user, test_user_b):
    note = await _make_poll_note(db, test_user.actor)
    await vote_on_poll(db, test_user_b, note.id, [1])
    data = await get_poll_data(db, note.id, test_user_b.actor_id)
    assert data["voted"] is True
    assert data["own_votes"] == [1]
    assert data["voters_count"] == 1
