from tests.conftest import make_remote_actor


async def test_handle_follow(db, test_user, mock_valkey):
    from app.activitypub.handlers.follow import handle_follow
    remote = await make_remote_actor(db, username="follower", domain="follower.example")
    activity = {
        "type": "Follow",
        "id": "http://follower.example/activities/follow1",
        "actor": remote.ap_id,
        "object": test_user.actor.ap_id,
    }
    await handle_follow(db, activity)
    from sqlalchemy import select
    from app.models.follow import Follow
    f = (await db.execute(select(Follow).where(
        Follow.follower_id == remote.id, Follow.following_id == test_user.actor_id
    ))).scalar_one_or_none()
    assert f is not None
    assert f.accepted is True  # auto-accept


async def test_handle_follow_auto_accept_enqueues(db, test_user, mock_valkey):
    from app.activitypub.handlers.follow import handle_follow
    remote = await make_remote_actor(db, username="fa", domain="fa.example")
    activity = {
        "type": "Follow",
        "id": "http://fa.example/activities/follow2",
        "actor": remote.ap_id,
        "object": test_user.actor.ap_id,
    }
    await handle_follow(db, activity)
    # Accept should be enqueued
    mock_valkey.lpush.assert_called()


async def test_handle_follow_duplicate_skipped(db, test_user, mock_valkey):
    from app.activitypub.handlers.follow import handle_follow
    remote = await make_remote_actor(db, username="dupf", domain="dupf.example")
    activity = {
        "type": "Follow",
        "id": "http://dupf.example/activities/follow3",
        "actor": remote.ap_id,
        "object": test_user.actor.ap_id,
    }
    await handle_follow(db, activity)
    await handle_follow(db, activity)  # Should not raise


async def test_handle_accept(db, test_user, mock_valkey):
    from app.activitypub.handlers.follow import handle_accept
    from app.models.follow import Follow
    remote = await make_remote_actor(db, username="acc", domain="acc.example")
    follow = Follow(
        follower_id=test_user.actor_id,
        following_id=remote.id,
        accepted=False,
        ap_id="http://localhost/activities/follow-pending",
    )
    db.add(follow)
    await db.flush()
    activity = {
        "type": "Accept",
        "actor": remote.ap_id,
        "object": {
            "type": "Follow",
            "actor": test_user.actor.ap_id,
            "object": remote.ap_id,
        }
    }
    await handle_accept(db, activity)
    await db.refresh(follow)
    assert follow.accepted is True


async def test_handle_reject(db, test_user, mock_valkey):
    from app.activitypub.handlers.follow import handle_reject
    from app.models.follow import Follow
    from sqlalchemy import select
    remote = await make_remote_actor(db, username="rej", domain="rej.example")
    follow = Follow(
        follower_id=test_user.actor_id,
        following_id=remote.id,
        accepted=False,
        ap_id="http://localhost/activities/follow-rej",
    )
    db.add(follow)
    await db.flush()
    activity = {
        "type": "Reject",
        "actor": remote.ap_id,
        "object": {
            "type": "Follow",
            "actor": test_user.actor.ap_id,
            "object": remote.ap_id,
        }
    }
    await handle_reject(db, activity)
    result = await db.execute(select(Follow).where(Follow.id == follow.id))
    assert result.scalar_one_or_none() is None
