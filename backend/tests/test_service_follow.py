import pytest

from app.models.follow import Follow
from tests.conftest import make_remote_actor


async def test_follow_local_auto_accepted(db, test_user, test_user_b, mock_valkey):
    from app.services.follow_service import follow_actor
    follow = await follow_actor(db, test_user, test_user_b.actor)
    assert follow.accepted is True


async def test_follow_remote_not_auto_accepted(db, test_user, mock_valkey):
    from app.services.follow_service import follow_actor
    remote = await make_remote_actor(db)
    follow = await follow_actor(db, test_user, remote)
    assert follow.accepted is False


async def test_follow_remote_enqueues_delivery(db, test_user, mock_valkey):
    from app.services.follow_service import follow_actor
    remote = await make_remote_actor(db)
    await follow_actor(db, test_user, remote)
    mock_valkey.lpush.assert_called()


async def test_follow_duplicate_raises(db, test_user, test_user_b, mock_valkey):
    from app.services.follow_service import follow_actor
    await follow_actor(db, test_user, test_user_b.actor)
    with pytest.raises(ValueError, match="Already following"):
        await follow_actor(db, test_user, test_user_b.actor)


async def test_unfollow(db, test_user, test_user_b, mock_valkey):
    from app.services.follow_service import follow_actor, unfollow_actor
    await follow_actor(db, test_user, test_user_b.actor)
    await unfollow_actor(db, test_user, test_user_b.actor)


async def test_unfollow_not_following_raises(db, test_user, test_user_b, mock_valkey):
    from app.services.follow_service import unfollow_actor
    with pytest.raises(ValueError, match="Not following"):
        await unfollow_actor(db, test_user, test_user_b.actor)


async def test_unfollow_remote_enqueues_undo(db, test_user, mock_valkey):
    from app.services.follow_service import follow_actor, unfollow_actor
    remote = await make_remote_actor(db)
    await follow_actor(db, test_user, remote)
    mock_valkey.lpush.reset_mock()
    await unfollow_actor(db, test_user, remote)
    mock_valkey.lpush.assert_called()


async def test_get_follower_inboxes_deduplicates(db, test_user, mock_valkey):
    from app.services.follow_service import get_follower_inboxes
    remote1 = await make_remote_actor(db, username="r1", domain="remote.example")
    remote2 = await make_remote_actor(db, username="r2", domain="remote.example")
    f1 = Follow(follower_id=remote1.id, following_id=test_user.actor_id, accepted=True)
    f2 = Follow(follower_id=remote2.id, following_id=test_user.actor_id, accepted=True)
    db.add_all([f1, f2])
    await db.flush()
    inboxes = await get_follower_inboxes(db, test_user.actor_id)
    # Both share "http://remote.example/inbox" as shared_inbox
    assert len(inboxes) == 1
