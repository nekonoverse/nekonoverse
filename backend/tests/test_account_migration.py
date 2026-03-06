"""Tests for account migration (Move activity)."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models.follow import Follow
from tests.conftest import make_remote_actor


@pytest.mark.asyncio
async def test_handle_incoming_move(db):
    """Move activity should set movedTo and migrate followers."""
    source = await make_remote_actor(db, username="alice", domain="old.example")
    target = await make_remote_actor(db, username="alice", domain="new.example")

    # Set alsoKnownAs on target
    target.also_known_as = [source.ap_id]
    await db.flush()

    # Create a local follower
    from app.models.actor import Actor
    from app.utils.crypto import generate_rsa_keypair
    _, pub = generate_rsa_keypair()

    local_actor = Actor(
        ap_id="http://localhost/users/localfan",
        username="localfan",
        domain=None,
        inbox_url="http://localhost/users/localfan/inbox",
        public_key_pem=pub,
    )
    db.add(local_actor)
    await db.flush()

    # Follow source
    follow = Follow(
        follower_id=local_actor.id,
        following_id=source.id,
        accepted=True,
    )
    db.add(follow)
    await db.commit()

    # Handle Move
    from app.services.move_service import handle_incoming_move
    result = await handle_incoming_move(db, source, target.ap_id)
    assert result is True

    # Source should have movedTo set
    await db.refresh(source)
    assert source.moved_to_ap_id == target.ap_id

    # Local follower should now follow target
    new_follow = await db.execute(
        select(Follow).where(
            Follow.follower_id == local_actor.id,
            Follow.following_id == target.id,
        )
    )
    assert new_follow.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_move_rejected_without_also_known_as(db):
    """Move should be rejected if target doesn't include source in alsoKnownAs."""
    source = await make_remote_actor(db, username="bob", domain="old2.example")
    target = await make_remote_actor(db, username="bob", domain="new2.example")
    # No alsoKnownAs set on target

    from app.services.move_service import handle_incoming_move
    result = await handle_incoming_move(db, source, target.ap_id)
    assert result is False

    await db.refresh(source)
    assert source.moved_to_ap_id is None


@pytest.mark.asyncio
async def test_move_no_duplicate_follows(db):
    """If follower already follows target, don't create duplicate."""
    source = await make_remote_actor(db, username="carol", domain="old3.example")
    target = await make_remote_actor(db, username="carol", domain="new3.example")
    target.also_known_as = [source.ap_id]
    await db.flush()

    from app.models.actor import Actor
    from app.utils.crypto import generate_rsa_keypair
    _, pub = generate_rsa_keypair()
    local = Actor(
        ap_id="http://localhost/users/fan2",
        username="fan2",
        domain=None,
        inbox_url="http://localhost/users/fan2/inbox",
        public_key_pem=pub,
    )
    db.add(local)
    await db.flush()

    # Follow both source and target
    db.add(Follow(follower_id=local.id, following_id=source.id, accepted=True))
    db.add(Follow(follower_id=local.id, following_id=target.id, accepted=True))
    await db.commit()

    from app.services.move_service import handle_incoming_move
    result = await handle_incoming_move(db, source, target.ap_id)
    assert result is True

    # Still only one follow to target
    from sqlalchemy import func
    count_result = await db.execute(
        select(func.count()).select_from(Follow).where(
            Follow.follower_id == local.id,
            Follow.following_id == target.id,
        )
    )
    assert count_result.scalar() == 1


@pytest.mark.asyncio
async def test_incoming_move_activity_handler(db):
    """Test the AP handler for Move activities."""
    source = await make_remote_actor(db, username="mover", domain="move.example")
    target = await make_remote_actor(db, username="mover", domain="newmove.example")
    target.also_known_as = [source.ap_id]
    await db.commit()

    from app.activitypub.handlers.move import handle_move
    activity = {
        "type": "Move",
        "actor": source.ap_id,
        "object": source.ap_id,
        "target": target.ap_id,
    }
    await handle_move(db, activity)

    await db.refresh(source)
    assert source.moved_to_ap_id == target.ap_id


@pytest.mark.asyncio
async def test_render_move_activity():
    from app.activitypub.renderer import render_move_activity
    data = render_move_activity(
        "http://localhost/move/1",
        "http://localhost/users/alice",
        "http://new.example/users/alice",
    )
    assert data["type"] == "Move"
    assert data["actor"] == "http://localhost/users/alice"
    assert data["target"] == "http://new.example/users/alice"


@pytest.mark.asyncio
async def test_render_add_remove_activity():
    from app.activitypub.renderer import render_add_activity, render_remove_activity
    add = render_add_activity(
        "http://localhost/add/1",
        "http://localhost/users/alice",
        "http://localhost/notes/123",
        "http://localhost/users/alice/featured",
    )
    assert add["type"] == "Add"
    assert add["target"] == "http://localhost/users/alice/featured"

    remove = render_remove_activity(
        "http://localhost/remove/1",
        "http://localhost/users/alice",
        "http://localhost/notes/123",
        "http://localhost/users/alice/featured",
    )
    assert remove["type"] == "Remove"


@pytest.mark.asyncio
async def test_move_handler_in_process_inbox(db):
    """Move should be in the handler map."""
    from app.activitypub.routes import process_inbox_activity

    source = await make_remote_actor(db, username="moveinbox", domain="inmove.example")
    target = await make_remote_actor(db, username="moveinbox", domain="outmove.example")
    target.also_known_as = [source.ap_id]
    await db.commit()

    activity = {
        "id": f"{source.ap_id}/move/1",
        "type": "Move",
        "actor": source.ap_id,
        "object": source.ap_id,
        "target": target.ap_id,
    }
    # Should not raise
    with patch("app.valkey_client.valkey") as mock_valkey:
        mock_valkey.set = AsyncMock(return_value=True)
        await process_inbox_activity(db, activity)

    await db.refresh(source)
    assert source.moved_to_ap_id == target.ap_id
