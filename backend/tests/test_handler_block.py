"""Tests for Block activity handler."""

from sqlalchemy import select

from app.models.follow import Follow
from app.models.user_block import UserBlock
from tests.conftest import make_remote_actor


async def test_handle_block_creates_block(db, test_user, mock_valkey):
    """Incoming Block activity should create a UserBlock record."""
    from app.activitypub.handlers.block import handle_block

    blocker = await make_remote_actor(db, username="blocker", domain="blocker.example")
    activity = {
        "type": "Block",
        "actor": blocker.ap_id,
        "object": test_user.actor.ap_id,
    }
    await handle_block(db, activity)

    result = await db.execute(
        select(UserBlock).where(
            UserBlock.actor_id == blocker.id,
            UserBlock.target_id == test_user.actor_id,
        )
    )
    assert result.scalar_one_or_none() is not None


async def test_handle_block_removes_follows(db, test_user, mock_valkey):
    """Block should remove follows in both directions."""
    from app.activitypub.handlers.block import handle_block

    blocker = await make_remote_actor(db, username="blocker2", domain="blocker2.example")

    # Create follows in both directions
    follow1 = Follow(follower_id=blocker.id, following_id=test_user.actor_id, accepted=True)
    follow2 = Follow(follower_id=test_user.actor_id, following_id=blocker.id, accepted=True)
    db.add(follow1)
    db.add(follow2)
    await db.flush()

    activity = {
        "type": "Block",
        "actor": blocker.ap_id,
        "object": test_user.actor.ap_id,
    }
    await handle_block(db, activity)

    # Both follows should be removed
    result = await db.execute(
        select(Follow).where(
            Follow.follower_id.in_([blocker.id, test_user.actor_id]),
            Follow.following_id.in_([blocker.id, test_user.actor_id]),
        )
    )
    assert result.scalars().all() == []


async def test_handle_block_idempotent(db, test_user, mock_valkey):
    """Blocking the same user twice should not create duplicate records."""
    from app.activitypub.handlers.block import handle_block

    blocker = await make_remote_actor(db, username="blocker3", domain="blocker3.example")
    activity = {
        "type": "Block",
        "actor": blocker.ap_id,
        "object": test_user.actor.ap_id,
    }
    await handle_block(db, activity)
    await handle_block(db, activity)

    result = await db.execute(
        select(UserBlock).where(
            UserBlock.actor_id == blocker.id,
            UserBlock.target_id == test_user.actor_id,
        )
    )
    assert len(result.scalars().all()) == 1


async def test_handle_block_missing_actor(db, test_user, mock_valkey):
    """Block without actor field should be silently ignored."""
    from app.activitypub.handlers.block import handle_block

    activity = {
        "type": "Block",
        "object": test_user.actor.ap_id,
    }
    await handle_block(db, activity)

    result = await db.execute(select(UserBlock))
    assert result.scalar_one_or_none() is None


async def test_handle_block_missing_object(db, mock_valkey):
    """Block without object field should be silently ignored."""
    from app.activitypub.handlers.block import handle_block

    blocker = await make_remote_actor(db, username="blocker4", domain="blocker4.example")
    activity = {
        "type": "Block",
        "actor": blocker.ap_id,
    }
    await handle_block(db, activity)

    result = await db.execute(select(UserBlock))
    assert result.scalar_one_or_none() is None


async def test_handle_block_unknown_actors(db, mock_valkey):
    """Block with unknown actor or target should be silently ignored."""
    from app.activitypub.handlers.block import handle_block

    activity = {
        "type": "Block",
        "actor": "http://unknown.example/users/nobody",
        "object": "http://unknown2.example/users/nobody2",
    }
    await handle_block(db, activity)

    result = await db.execute(select(UserBlock))
    assert result.scalar_one_or_none() is None
