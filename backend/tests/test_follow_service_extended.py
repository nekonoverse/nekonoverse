"""Extended tests for follow_service — follow/unfollow, get lists."""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.follow import Follow
from app.services.follow_service import (
    follow_actor,
    get_follow_counts,
    get_follower_ids,
    get_follower_inboxes,
    get_followers,
    get_following,
    get_following_ids,
    unfollow_actor,
)
from tests.conftest import make_remote_actor


async def test_follow_local_actor(db, mock_valkey, test_user, test_user_b):
    """Following a local actor is auto-accepted and creates notification."""
    follow = await follow_actor(db, test_user, test_user_b.actor)
    assert follow.accepted is True
    assert follow.follower_id == test_user.actor_id
    assert follow.following_id == test_user_b.actor_id


async def test_follow_unlocked_creates_follow_notification(db, mock_valkey, test_user, test_user_b):
    """Following an unlocked local actor creates a 'follow' notification."""
    from sqlalchemy import select
    from app.models.notification import Notification

    await follow_actor(db, test_user, test_user_b.actor)
    result = await db.execute(
        select(Notification).where(
            Notification.recipient_id == test_user_b.actor_id,
            Notification.sender_id == test_user.actor_id,
        )
    )
    notif = result.scalar_one()
    assert notif.type == "follow"


async def test_follow_locked_creates_follow_request_notification(db, mock_valkey, test_user, test_user_b):
    """Following a locked local actor creates a 'follow_request' notification."""
    from sqlalchemy import select
    from app.models.notification import Notification

    # Lock the target account
    test_user_b.actor.manually_approves_followers = True
    await db.flush()

    follow = await follow_actor(db, test_user, test_user_b.actor)
    assert follow.accepted is False

    result = await db.execute(
        select(Notification).where(
            Notification.recipient_id == test_user_b.actor_id,
            Notification.sender_id == test_user.actor_id,
        )
    )
    notif = result.scalar_one()
    assert notif.type == "follow_request"


async def test_follow_remote_actor(db, mock_valkey, test_user):
    """Following a remote actor delivers Follow activity."""
    remote = await make_remote_actor(db, username="rem_follow", domain="follow.example")
    with patch(
        "app.services.follow_service.enqueue_delivery",
        new_callable=AsyncMock,
    ) as mock_deliver:
        follow = await follow_actor(db, test_user, remote)
    assert follow.accepted is False
    mock_deliver.assert_called_once()


async def test_follow_duplicate_raises(db, mock_valkey, test_user, test_user_b):
    await follow_actor(db, test_user, test_user_b.actor)
    with pytest.raises(ValueError, match="Already following"):
        await follow_actor(db, test_user, test_user_b.actor)


async def test_unfollow_local_actor(db, mock_valkey, test_user, test_user_b):
    await follow_actor(db, test_user, test_user_b.actor)
    await unfollow_actor(db, test_user, test_user_b.actor)
    ids = await get_following_ids(db, test_user.actor_id)
    assert test_user_b.actor_id not in ids


async def test_unfollow_remote_actor(db, mock_valkey, test_user):
    """Unfollowing a remote actor delivers Undo(Follow)."""
    remote = await make_remote_actor(db, username="rem_unf", domain="unfollow.example")
    with patch(
        "app.services.follow_service.enqueue_delivery",
        new_callable=AsyncMock,
    ):
        await follow_actor(db, test_user, remote)
    # Accept the follow for this test
    from sqlalchemy import select

    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == test_user.actor_id,
            Follow.following_id == remote.id,
        )
    )
    f = result.scalar_one()
    f.accepted = True
    await db.flush()

    with patch(
        "app.services.follow_service.enqueue_delivery",
        new_callable=AsyncMock,
    ) as mock_deliver:
        await unfollow_actor(db, test_user, remote)
    mock_deliver.assert_called_once()


async def test_unfollow_not_following_raises(db, mock_valkey, test_user, test_user_b):
    with pytest.raises(ValueError, match="Not following"):
        await unfollow_actor(db, test_user, test_user_b.actor)


async def test_get_follower_ids(db, mock_valkey, test_user, test_user_b):
    await follow_actor(db, test_user, test_user_b.actor)
    ids = await get_follower_ids(db, test_user_b.actor_id)
    assert test_user.actor_id in ids


async def test_get_following_ids(db, mock_valkey, test_user, test_user_b):
    await follow_actor(db, test_user, test_user_b.actor)
    ids = await get_following_ids(db, test_user.actor_id)
    assert test_user_b.actor_id in ids


async def test_get_followers(db, mock_valkey, test_user, test_user_b):
    await follow_actor(db, test_user, test_user_b.actor)
    followers = await get_followers(db, test_user_b.actor_id)
    assert any(a.id == test_user.actor_id for a in followers)


async def test_get_following(db, mock_valkey, test_user, test_user_b):
    await follow_actor(db, test_user, test_user_b.actor)
    following = await get_following(db, test_user.actor_id)
    assert any(a.id == test_user_b.actor_id for a in following)


async def test_get_follow_counts(db, mock_valkey, test_user, test_user_b):
    await follow_actor(db, test_user, test_user_b.actor)
    followers_count, following_count = await get_follow_counts(db, test_user_b.actor_id)
    assert followers_count >= 1
    f_count, fg_count = await get_follow_counts(db, test_user.actor_id)
    assert fg_count >= 1


async def test_get_follower_inboxes(db, mock_valkey, test_user):
    """Returns inbox URLs of remote followers."""
    remote = await make_remote_actor(db, username="inbox_fol", domain="inbox.example")
    follow = Follow(
        follower_id=remote.id,
        following_id=test_user.actor_id,
        accepted=True,
    )
    db.add(follow)
    await db.flush()

    inboxes = await get_follower_inboxes(db, test_user.actor_id)
    assert len(inboxes) >= 1
    # shared_inboxが優先される
    assert remote.shared_inbox_url in inboxes
