"""Extended tests for note_service — visibility checks, timelines, mentions."""

import uuid

from app.models.follow import Follow
from app.services.note_service import (
    check_note_visible,
    extract_mentions,
    get_home_timeline,
    get_note_by_ap_id,
    get_note_by_id,
    get_public_timeline,
    get_reaction_summaries,
    get_reaction_summary,
)
from tests.conftest import make_note, make_remote_actor

# ── extract_mentions ─────────────────────────────────────────────────────


def test_extract_local_mention():
    mentions = extract_mentions("Hello @alice how are you?")
    assert ("alice", None) in mentions


def test_extract_remote_mention():
    mentions = extract_mentions("cc @bob@remote.example")
    assert ("bob", "remote.example") in mentions


def test_extract_multiple_mentions():
    mentions = extract_mentions("@alice @bob@remote.example hello")
    assert len(mentions) == 2


def test_extract_no_mentions():
    mentions = extract_mentions("no mentions here")
    assert mentions == []


# ── check_note_visible ───────────────────────────────────────────────────


async def test_visible_public_note(db, mock_valkey, test_user):
    note = await make_note(db, test_user.actor, visibility="public")
    assert await check_note_visible(db, note) is True


async def test_visible_unlisted_note(db, mock_valkey, test_user):
    note = await make_note(db, test_user.actor, visibility="unlisted")
    assert await check_note_visible(db, note) is True


async def test_visible_own_note_always(db, mock_valkey, test_user):
    """Author can always see their own note regardless of visibility."""
    note = await make_note(db, test_user.actor, visibility="direct")
    assert await check_note_visible(db, note, test_user.actor_id) is True


async def test_followers_note_invisible_to_anon(db, mock_valkey, test_user):
    note = await make_note(db, test_user.actor, visibility="followers")
    assert await check_note_visible(db, note) is False


async def test_followers_note_invisible_to_non_follower(db, mock_valkey, test_user, test_user_b):
    note = await make_note(db, test_user.actor, visibility="followers")
    assert await check_note_visible(db, note, test_user_b.actor_id) is False


async def test_followers_note_visible_to_follower(db, mock_valkey, test_user, test_user_b):
    """Follower can see followers-only note."""
    follow = Follow(
        follower_id=test_user_b.actor_id,
        following_id=test_user.actor_id,
        accepted=True,
    )
    db.add(follow)
    await db.flush()

    note = await make_note(db, test_user.actor, visibility="followers")
    assert await check_note_visible(db, note, test_user_b.actor_id) is True


async def test_direct_note_invisible_to_anon(db, mock_valkey, test_user):
    note = await make_note(db, test_user.actor, visibility="direct")
    assert await check_note_visible(db, note) is False


async def test_direct_note_invisible_to_non_mentioned(db, mock_valkey, test_user, test_user_b):
    note = await make_note(db, test_user.actor, visibility="direct")
    # No mentions set, so test_user_b can't see it
    assert await check_note_visible(db, note, test_user_b.actor_id) is False


# ── get_note_by_id / get_note_by_ap_id ───────────────────────────────────


async def test_get_note_by_id(db, mock_valkey, test_user):
    note = await make_note(db, test_user.actor, content="find me")
    found = await get_note_by_id(db, note.id)
    assert found is not None
    assert found.id == note.id


async def test_get_note_by_id_not_found(db, mock_valkey):
    found = await get_note_by_id(db, uuid.uuid4())
    assert found is None


async def test_get_note_by_ap_id(db, mock_valkey, test_user):
    note = await make_note(db, test_user.actor, content="ap lookup")
    found = await get_note_by_ap_id(db, note.ap_id)
    assert found is not None
    assert found.id == note.id


# ── get_public_timeline ──────────────────────────────────────────────────


async def test_public_timeline_returns_public_notes(db, mock_valkey, test_user):
    await make_note(db, test_user.actor, content="public note", visibility="public")
    notes = await get_public_timeline(db, limit=10)
    assert len(notes) >= 1


async def test_public_timeline_excludes_non_public(db, mock_valkey, test_user):
    await make_note(db, test_user.actor, content="followers only", visibility="followers")
    notes = await get_public_timeline(db, limit=50)
    contents = [n.source or "" for n in notes]
    assert not any("followers only" in c for c in contents)


async def test_public_timeline_pagination(db, mock_valkey, test_user):
    for i in range(5):
        await make_note(db, test_user.actor, content=f"timeline {i}")
    notes = await get_public_timeline(db, limit=2)
    assert len(notes) <= 2


async def test_public_timeline_local_only(db, mock_valkey, test_user):
    remote_actor = await make_remote_actor(db, username="remote_tl", domain="tl.example")
    await make_note(db, remote_actor, content="remote note", local=False)
    await make_note(db, test_user.actor, content="local note")

    notes = await get_public_timeline(db, limit=50, local_only=True)
    for n in notes:
        assert n.local is True


# ── get_home_timeline ────────────────────────────────────────────────────


async def test_home_timeline_includes_own_and_followed(db, mock_valkey, test_user, test_user_b):
    follow = Follow(
        follower_id=test_user.actor_id,
        following_id=test_user_b.actor_id,
        accepted=True,
    )
    db.add(follow)
    await db.flush()

    await make_note(db, test_user.actor, content="my own note")
    await make_note(db, test_user_b.actor, content="followed user note")

    notes = await get_home_timeline(db, test_user, limit=50)
    sources = [n.source or "" for n in notes]
    assert any("my own note" in s for s in sources)
    assert any("followed user note" in s for s in sources)


# ── get_reaction_summary / get_reaction_summaries ────────────────────────


async def test_reaction_summary_empty(db, mock_valkey, test_user):
    note = await make_note(db, test_user.actor, content="no reactions")
    summary = await get_reaction_summary(db, note.id)
    assert summary == []


async def test_reaction_summary_with_reaction(db, mock_valkey, test_user, test_user_b):
    from app.services.reaction_service import add_reaction

    note = await make_note(db, test_user.actor, content="react to me")
    await add_reaction(db, test_user_b, note, "\u2764\ufe0f")

    summary = await get_reaction_summary(db, note.id)
    assert len(summary) >= 1
    assert summary[0]["emoji"] == "\u2764\ufe0f"
    assert summary[0]["count"] >= 1


async def test_reaction_summaries_batch(db, mock_valkey, test_user, test_user_b):
    from app.services.reaction_service import add_reaction

    note1 = await make_note(db, test_user.actor, content="note1")
    note2 = await make_note(db, test_user.actor, content="note2")
    await add_reaction(db, test_user_b, note1, "\U0001f44d")

    summaries = await get_reaction_summaries(db, [note1.id, note2.id])
    assert note1.id in summaries
    assert note2.id in summaries
    assert len(summaries[note1.id]) >= 1
    assert len(summaries[note2.id]) == 0
