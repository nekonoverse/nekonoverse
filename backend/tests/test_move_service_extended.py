"""Extended tests for move_service — account migration."""

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from sqlalchemy import select

from app.models.follow import Follow
from app.services.move_service import handle_incoming_move, initiate_move
from tests.conftest import make_remote_actor

# handle_incoming_move と initiate_move は fetch_remote_actor をローカルインポートしているため、
# パッチ対象は元モジュール (actor_service) にする
_FETCH_PATCH = "app.services.actor_service.fetch_remote_actor"


async def test_incoming_move_success(db, mock_valkey, test_user):
    """Incoming move migrates local followers to target."""
    source = await make_remote_actor(db, username="source_m", domain="old.example")
    target = await make_remote_actor(db, username="target_m", domain="new.example")
    target.also_known_as = [source.ap_id]
    await db.flush()

    # test_user follows source
    follow = Follow(follower_id=test_user.actor_id, following_id=source.id, accepted=True)
    db.add(follow)
    await db.flush()

    with patch(_FETCH_PATCH, new_callable=AsyncMock, return_value=target):
        result = await handle_incoming_move(db, source, target.ap_id)
    assert result is True
    assert source.moved_to_ap_id == target.ap_id


async def test_incoming_move_no_also_known_as(db, mock_valkey):
    """Move rejected when target lacks alsoKnownAs for source."""
    source = await make_remote_actor(db, username="src_no_aka", domain="old2.example")
    target = await make_remote_actor(db, username="tgt_no_aka", domain="new2.example")
    target.also_known_as = []
    await db.flush()

    with patch(_FETCH_PATCH, new_callable=AsyncMock, return_value=target):
        result = await handle_incoming_move(db, source, target.ap_id)
    assert result is False


async def test_incoming_move_target_not_found(db, mock_valkey):
    """Move fails when target actor can't be fetched."""
    source = await make_remote_actor(db, username="src_nf", domain="old3.example")

    with patch(_FETCH_PATCH, new_callable=AsyncMock, return_value=None):
        result = await handle_incoming_move(db, source, "https://gone.example/users/x")
    assert result is False


async def test_incoming_move_no_duplicate_follows(db, mock_valkey, test_user):
    """Move doesn't create duplicate follows if already following target."""
    source = await make_remote_actor(db, username="src_dup", domain="old4.example")
    target = await make_remote_actor(db, username="tgt_dup", domain="new4.example")
    target.also_known_as = [source.ap_id]
    await db.flush()

    # Already following both source and target
    db.add(Follow(follower_id=test_user.actor_id, following_id=source.id, accepted=True))
    db.add(Follow(follower_id=test_user.actor_id, following_id=target.id, accepted=True))
    await db.flush()

    with patch(_FETCH_PATCH, new_callable=AsyncMock, return_value=target):
        result = await handle_incoming_move(db, source, target.ap_id)
    assert result is True


async def test_initiate_move_success(db, mock_valkey, test_user):
    """Local user initiates move with valid target."""
    target = await make_remote_actor(db, username="tgt_init", domain="newhome.example")
    from app.services.actor_service import actor_uri

    target.also_known_as = [actor_uri(test_user.actor)]
    await db.flush()

    with (
        patch(_FETCH_PATCH, new_callable=AsyncMock, return_value=target),
        patch(
            "app.services.follow_service.get_follower_inboxes",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        result = await initiate_move(db, test_user, target.ap_id)
    assert result is True
    assert test_user.actor.moved_to_ap_id == target.ap_id


async def test_initiate_move_target_not_found(db, mock_valkey, test_user):
    with patch(_FETCH_PATCH, new_callable=AsyncMock, return_value=None):
        with pytest.raises(ValueError, match="Target actor not found"):
            await initiate_move(db, test_user, "https://gone.example/users/x")


async def test_initiate_move_no_also_known_as(db, mock_valkey, test_user):
    target = await make_remote_actor(db, username="tgt_noaka", domain="noaka.example")
    target.also_known_as = []
    await db.flush()

    with patch(_FETCH_PATCH, new_callable=AsyncMock, return_value=target):
        with pytest.raises(ValueError, match="alsoKnownAs"):
            await initiate_move(db, test_user, target.ap_id)


async def test_incoming_move_creates_notification(db, mock_valkey, test_user):
    """Move はローカルフォロワーに move 通知を作成する。"""
    source = await make_remote_actor(db, username="src_notif", domain="old5.example")
    target = await make_remote_actor(db, username="tgt_notif", domain="new5.example")
    target.also_known_as = [source.ap_id]
    await db.flush()

    # test_user が source をフォロー
    db.add(Follow(follower_id=test_user.actor_id, following_id=source.id, accepted=True))
    await db.flush()

    with (
        patch(_FETCH_PATCH, new_callable=AsyncMock, return_value=target),
        patch(
            "app.services.notification_service.create_notification",
            new_callable=AsyncMock,
        ) as mock_notify,
    ):
        result = await handle_incoming_move(db, source, target.ap_id)

    assert result is True
    # ローカルフォロワー (test_user) に move 通知が作成されること
    mock_notify.assert_called_once()
    _, kwargs = mock_notify.call_args
    assert kwargs["type"] == "move"
    assert kwargs["recipient_id"] == test_user.actor_id
    assert kwargs["sender_id"] == source.id


async def test_incoming_move_sends_follow_to_remote_target(db, mock_valkey, test_user):
    """Move でローカルフォロワーからリモート移行先へ Follow Activity を配送する。"""
    source = await make_remote_actor(db, username="src_fwd", domain="old6.example")
    target = await make_remote_actor(db, username="tgt_fwd", domain="new6.example")
    target.also_known_as = [source.ap_id]
    await db.flush()

    # test_user が source をフォロー
    db.add(Follow(follower_id=test_user.actor_id, following_id=source.id, accepted=True))
    await db.flush()

    with (
        patch(_FETCH_PATCH, new_callable=AsyncMock, return_value=target),
        patch(
            "app.services.notification_service.create_notification",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.delivery_service.enqueue_delivery",
            new_callable=AsyncMock,
        ) as mock_delivery,
        patch(
            "app.activitypub.renderer.render_follow_activity",
            return_value={"type": "Follow"},
        ) as mock_render,
    ):
        result = await handle_incoming_move(db, source, target.ap_id)

    assert result is True
    # ローカルフォロワーからリモート target への Follow が配送されること
    mock_delivery.assert_called_once()
    delivery_args = mock_delivery.call_args
    assert delivery_args[0][1] == test_user.actor_id  # sender = follower
    assert delivery_args[0][2] == target.inbox_url  # inbox
    mock_render.assert_called_once()


async def test_incoming_move_no_delivery_for_local_target(db, mock_valkey, test_user):
    """移行先がローカルの場合は Follow Activity を配送しない。"""
    source = await make_remote_actor(db, username="src_loc", domain="old7.example")

    # ローカルの移行先ユーザーを作成
    from app.services.user_service import create_user
    target_user = await create_user(
        db, "tgt_local", "tgt@example.com", "password1234", display_name="Target Local"
    )
    target_actor = target_user.actor
    target_actor.also_known_as = [source.ap_id]
    await db.flush()

    # test_user が source をフォロー
    db.add(Follow(follower_id=test_user.actor_id, following_id=source.id, accepted=True))
    await db.flush()

    with (
        patch(_FETCH_PATCH, new_callable=AsyncMock, return_value=target_actor),
        patch(
            "app.services.notification_service.create_notification",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.delivery_service.enqueue_delivery",
            new_callable=AsyncMock,
        ) as mock_delivery,
    ):
        result = await handle_incoming_move(db, source, target_actor.ap_id)

    assert result is True
    # ローカル target には Follow Activity を配送しない
    mock_delivery.assert_not_called()
