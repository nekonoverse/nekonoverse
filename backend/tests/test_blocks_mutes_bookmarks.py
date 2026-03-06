"""Tests for blocks, mutes, and bookmarks (Phase 4)."""

import uuid
from unittest.mock import AsyncMock

import pytest

from tests.conftest import make_note, make_remote_actor


# ── Helpers ──────────────────────────────────────────────────────────────────


def authed_client_for(app_client, mock_valkey, user):
    mock_valkey.get = AsyncMock(return_value=str(user.id))
    app_client.cookies.set("nekonoverse_session", "test-session-id")
    return app_client


# ── Block Service ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_block_actor_service(db, mock_valkey, test_user, test_user_b):
    from app.services.block_service import block_actor, is_blocking

    await block_actor(db, test_user, test_user_b.actor)
    await db.commit()

    assert await is_blocking(db, test_user.actor_id, test_user_b.actor_id)
    assert not await is_blocking(db, test_user_b.actor_id, test_user.actor_id)


@pytest.mark.anyio
async def test_block_removes_follows(db, mock_valkey, test_user, test_user_b):
    """Blocking should remove follows in both directions."""
    from app.services.block_service import block_actor
    from app.services.follow_service import follow_actor

    # Set up mutual follow
    await follow_actor(db, test_user, test_user_b.actor)
    await follow_actor(db, test_user_b, test_user.actor)

    # Block should remove both
    await block_actor(db, test_user, test_user_b.actor)
    await db.commit()

    from sqlalchemy import select
    from app.models.follow import Follow

    result = await db.execute(
        select(Follow).where(
            ((Follow.follower_id == test_user.actor_id) & (Follow.following_id == test_user_b.actor_id))
            | ((Follow.follower_id == test_user_b.actor_id) & (Follow.following_id == test_user.actor_id))
        )
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.anyio
async def test_block_already_blocking(db, mock_valkey, test_user, test_user_b):
    from app.services.block_service import block_actor

    await block_actor(db, test_user, test_user_b.actor)
    await db.commit()

    with pytest.raises(ValueError, match="Already blocking"):
        await block_actor(db, test_user, test_user_b.actor)


@pytest.mark.anyio
async def test_unblock_actor_service(db, mock_valkey, test_user, test_user_b):
    from app.services.block_service import block_actor, is_blocking, unblock_actor

    await block_actor(db, test_user, test_user_b.actor)
    await db.commit()

    await unblock_actor(db, test_user, test_user_b.actor)
    await db.commit()

    assert not await is_blocking(db, test_user.actor_id, test_user_b.actor_id)


@pytest.mark.anyio
async def test_unblock_not_blocking(db, mock_valkey, test_user, test_user_b):
    from app.services.block_service import unblock_actor

    with pytest.raises(ValueError, match="Not blocking"):
        await unblock_actor(db, test_user, test_user_b.actor)


@pytest.mark.anyio
async def test_get_blocked_ids(db, mock_valkey, test_user, test_user_b):
    from app.services.block_service import block_actor, get_blocked_ids

    await block_actor(db, test_user, test_user_b.actor)
    await db.commit()

    ids = await get_blocked_ids(db, test_user.actor_id)
    assert test_user_b.actor_id in ids


# ── Block API ────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_block_api(db, app_client, mock_valkey, test_user, test_user_b):
    client = authed_client_for(app_client, mock_valkey, test_user)

    resp = await client.post(f"/api/v1/accounts/{test_user_b.actor_id}/block")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_block_self_forbidden(db, app_client, mock_valkey, test_user):
    client = authed_client_for(app_client, mock_valkey, test_user)

    resp = await client.post(f"/api/v1/accounts/{test_user.actor_id}/block")
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_unblock_api(db, app_client, mock_valkey, test_user, test_user_b):
    client = authed_client_for(app_client, mock_valkey, test_user)

    await client.post(f"/api/v1/accounts/{test_user_b.actor_id}/block")
    resp = await client.post(f"/api/v1/accounts/{test_user_b.actor_id}/unblock")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_list_blocks_api(db, app_client, mock_valkey, test_user, test_user_b):
    client = authed_client_for(app_client, mock_valkey, test_user)

    await client.post(f"/api/v1/accounts/{test_user_b.actor_id}/block")

    resp = await client.get("/api/v1/blocks")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert any(a["username"] == "testuser_b" for a in data)


# ── Mute Service ─────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_mute_actor_service(db, mock_valkey, test_user, test_user_b):
    from app.services.mute_service import is_muting, mute_actor

    await mute_actor(db, test_user, test_user_b.actor)
    await db.commit()

    assert await is_muting(db, test_user.actor_id, test_user_b.actor_id)


@pytest.mark.anyio
async def test_mute_already_muting(db, mock_valkey, test_user, test_user_b):
    from app.services.mute_service import mute_actor

    await mute_actor(db, test_user, test_user_b.actor)
    await db.commit()

    with pytest.raises(ValueError, match="Already muting"):
        await mute_actor(db, test_user, test_user_b.actor)


@pytest.mark.anyio
async def test_unmute_actor_service(db, mock_valkey, test_user, test_user_b):
    from app.services.mute_service import is_muting, mute_actor, unmute_actor

    await mute_actor(db, test_user, test_user_b.actor)
    await db.commit()

    await unmute_actor(db, test_user, test_user_b.actor)
    await db.commit()

    assert not await is_muting(db, test_user.actor_id, test_user_b.actor_id)


@pytest.mark.anyio
async def test_get_muted_ids(db, mock_valkey, test_user, test_user_b):
    from app.services.mute_service import get_muted_ids, mute_actor

    await mute_actor(db, test_user, test_user_b.actor)
    await db.commit()

    ids = await get_muted_ids(db, test_user.actor_id)
    assert test_user_b.actor_id in ids


# ── Mute API ─────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_mute_api(db, app_client, mock_valkey, test_user, test_user_b):
    client = authed_client_for(app_client, mock_valkey, test_user)

    resp = await client.post(f"/api/v1/accounts/{test_user_b.actor_id}/mute")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_mute_self_forbidden(db, app_client, mock_valkey, test_user):
    client = authed_client_for(app_client, mock_valkey, test_user)

    resp = await client.post(f"/api/v1/accounts/{test_user.actor_id}/mute")
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_unmute_api(db, app_client, mock_valkey, test_user, test_user_b):
    client = authed_client_for(app_client, mock_valkey, test_user)

    await client.post(f"/api/v1/accounts/{test_user_b.actor_id}/mute")
    resp = await client.post(f"/api/v1/accounts/{test_user_b.actor_id}/unmute")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_list_mutes_api(db, app_client, mock_valkey, test_user, test_user_b):
    client = authed_client_for(app_client, mock_valkey, test_user)

    await client.post(f"/api/v1/accounts/{test_user_b.actor_id}/mute")

    resp = await client.get("/api/v1/mutes")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert any(a["username"] == "testuser_b" for a in data)


# ── Bookmark Service ─────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_create_bookmark(db, mock_valkey, test_user):
    from app.services.bookmark_service import create_bookmark, is_bookmarked

    note = await make_note(db, test_user.actor, content="Bookmark me")

    await create_bookmark(db, test_user.actor_id, note.id)
    await db.commit()

    assert await is_bookmarked(db, test_user.actor_id, note.id)


@pytest.mark.anyio
async def test_create_bookmark_duplicate(db, mock_valkey, test_user):
    from app.services.bookmark_service import create_bookmark

    note = await make_note(db, test_user.actor, content="Bookmark me")

    await create_bookmark(db, test_user.actor_id, note.id)
    await db.commit()

    with pytest.raises(ValueError, match="Already bookmarked"):
        await create_bookmark(db, test_user.actor_id, note.id)


@pytest.mark.anyio
async def test_remove_bookmark(db, mock_valkey, test_user):
    from app.services.bookmark_service import create_bookmark, is_bookmarked, remove_bookmark

    note = await make_note(db, test_user.actor, content="Bookmark me")

    await create_bookmark(db, test_user.actor_id, note.id)
    await db.commit()

    await remove_bookmark(db, test_user.actor_id, note.id)
    await db.commit()

    assert not await is_bookmarked(db, test_user.actor_id, note.id)


@pytest.mark.anyio
async def test_remove_bookmark_not_bookmarked(db, mock_valkey, test_user):
    from app.services.bookmark_service import remove_bookmark

    note = await make_note(db, test_user.actor, content="Not bookmarked")

    with pytest.raises(ValueError, match="Not bookmarked"):
        await remove_bookmark(db, test_user.actor_id, note.id)


@pytest.mark.anyio
async def test_get_bookmarks(db, mock_valkey, test_user):
    from app.services.bookmark_service import create_bookmark, get_bookmarks

    note1 = await make_note(db, test_user.actor, content="BM 1")
    note2 = await make_note(db, test_user.actor, content="BM 2")

    await create_bookmark(db, test_user.actor_id, note1.id)
    await create_bookmark(db, test_user.actor_id, note2.id)
    await db.commit()

    bookmarks = await get_bookmarks(db, test_user.actor_id)
    assert len(bookmarks) >= 2


# ── Bookmark API ─────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_bookmark_api(db, app_client, mock_valkey, test_user):
    client = authed_client_for(app_client, mock_valkey, test_user)
    note = await make_note(db, test_user.actor, content="Bookmark via API")

    resp = await client.post(f"/api/v1/statuses/{note.id}/bookmark")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_unbookmark_api(db, app_client, mock_valkey, test_user):
    client = authed_client_for(app_client, mock_valkey, test_user)
    note = await make_note(db, test_user.actor, content="Unbookmark via API")

    await client.post(f"/api/v1/statuses/{note.id}/bookmark")
    resp = await client.post(f"/api/v1/statuses/{note.id}/unbookmark")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_bookmark_nonexistent_note(db, app_client, mock_valkey, test_user):
    client = authed_client_for(app_client, mock_valkey, test_user)
    resp = await client.post(f"/api/v1/statuses/{uuid.uuid4()}/bookmark")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_list_bookmarks_api(db, app_client, mock_valkey, test_user):
    client = authed_client_for(app_client, mock_valkey, test_user)
    note = await make_note(db, test_user.actor, content="Bookmarked note")

    await client.post(f"/api/v1/statuses/{note.id}/bookmark")

    resp = await client.get("/api/v1/bookmarks")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1


# ── Timeline Block/Mute Filters ──────────────────────────────────────────────


@pytest.mark.anyio
async def test_blocked_user_excluded_from_home_timeline(db, mock_valkey, test_user, test_user_b):
    """Blocked user's notes should not appear in home timeline."""
    from app.services.block_service import block_actor
    from app.services.follow_service import follow_actor
    from app.services.note_service import get_home_timeline

    # Follow user_b first
    await follow_actor(db, test_user, test_user_b.actor)
    note_b = await make_note(db, test_user_b.actor, content="You can't see me")
    note_a = await make_note(db, test_user.actor, content="My own post")
    await db.commit()

    # Block user_b
    await block_actor(db, test_user, test_user_b.actor)
    await db.commit()

    timeline = await get_home_timeline(db, test_user, limit=50)
    note_ids = [n.id for n in timeline]
    assert note_a.id in note_ids
    assert note_b.id not in note_ids


@pytest.mark.anyio
async def test_muted_user_excluded_from_public_timeline(db, mock_valkey, test_user, test_user_b):
    """Muted user's notes should not appear in public timeline for the muting user."""
    from app.services.mute_service import mute_actor
    from app.services.note_service import get_public_timeline

    note_a = await make_note(db, test_user.actor, content="Normal post")
    note_b = await make_note(db, test_user_b.actor, content="Muted post")

    await mute_actor(db, test_user, test_user_b.actor)
    await db.commit()

    timeline = await get_public_timeline(db, limit=50, current_actor_id=test_user.actor_id)
    note_ids = [n.id for n in timeline]
    assert note_a.id in note_ids
    assert note_b.id not in note_ids


# ── AP Block Handler ─────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_handle_block(db, mock_valkey, test_user):
    """Incoming Block activity should create a UserBlock."""
    remote = await make_remote_actor(db, username="blocker", domain="other.example")

    from app.activitypub.handlers.block import handle_block

    activity = {
        "type": "Block",
        "actor": remote.ap_id,
        "object": test_user.actor.ap_id,
    }
    await handle_block(db, activity)

    from app.services.block_service import is_blocking
    assert await is_blocking(db, remote.id, test_user.actor_id)


@pytest.mark.anyio
async def test_handle_undo_block(db, mock_valkey, test_user):
    """Undo(Block) should remove the UserBlock."""
    remote = await make_remote_actor(db, username="unblocker", domain="unblock.example")

    from app.activitypub.handlers.block import handle_block

    activity = {
        "type": "Block",
        "actor": remote.ap_id,
        "object": test_user.actor.ap_id,
    }
    await handle_block(db, activity)

    from app.activitypub.handlers.undo import handle_undo

    undo_activity = {
        "type": "Undo",
        "actor": remote.ap_id,
        "object": {
            "type": "Block",
            "actor": remote.ap_id,
            "object": test_user.actor.ap_id,
        },
    }
    await handle_undo(db, undo_activity)

    from app.services.block_service import is_blocking
    assert not await is_blocking(db, remote.id, test_user.actor_id)


# ── Renderer ─────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_render_block_activity():
    from app.activitypub.renderer import render_block_activity

    result = render_block_activity(
        "https://local/blocks/1",
        "https://local/users/me",
        "https://remote/users/them",
    )
    assert result["type"] == "Block"
    assert result["actor"] == "https://local/users/me"
    assert result["object"] == "https://remote/users/them"
