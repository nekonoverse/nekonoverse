"""Extended tests for block_service — unblock and is_blocking."""

import pytest

from app.models.follow import Follow
from app.services.block_service import block_actor, is_blocking, unblock_actor
from tests.conftest import make_remote_actor


async def test_block_removes_mutual_follows(db, mock_valkey, test_user, test_user_b):
    """Blocking removes follows in both directions."""
    # Set up mutual follow
    f1 = Follow(follower_id=test_user.actor_id, following_id=test_user_b.actor_id, accepted=True)
    f2 = Follow(follower_id=test_user_b.actor_id, following_id=test_user.actor_id, accepted=True)
    db.add(f1)
    db.add(f2)
    await db.flush()

    await block_actor(db, test_user, test_user_b.actor)

    from sqlalchemy import select

    result = await db.execute(
        select(Follow).where(
            (
                (Follow.follower_id == test_user.actor_id)
                & (Follow.following_id == test_user_b.actor_id)
            )
            | (
                (Follow.follower_id == test_user_b.actor_id)
                & (Follow.following_id == test_user.actor_id)
            )
        )
    )
    assert result.scalar_one_or_none() is None


async def test_unblock_actor_success(db, mock_valkey, test_user, test_user_b):
    await block_actor(db, test_user, test_user_b.actor)
    await unblock_actor(db, test_user, test_user_b.actor)
    assert await is_blocking(db, test_user.actor_id, test_user_b.actor_id) is False


async def test_unblock_not_blocking_raises(db, mock_valkey, test_user, test_user_b):
    with pytest.raises(ValueError, match="Not blocking"):
        await unblock_actor(db, test_user, test_user_b.actor)


async def test_is_blocking(db, mock_valkey, test_user, test_user_b):
    assert await is_blocking(db, test_user.actor_id, test_user_b.actor_id) is False
    await block_actor(db, test_user, test_user_b.actor)
    assert await is_blocking(db, test_user.actor_id, test_user_b.actor_id) is True


async def test_block_remote_actor_delivers_activity(db, mock_valkey, test_user):
    """Blocking remote actor enqueues delivery."""
    remote = await make_remote_actor(db, username="blocked_remote", domain="block.example")
    await block_actor(db, test_user, remote)
    # Delivery should be enqueued (lpush called on Valkey)
    mock_valkey.lpush.assert_called()
