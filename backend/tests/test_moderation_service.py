"""Tests for moderation_service."""

from unittest.mock import AsyncMock, patch

from app.services.moderation_service import (
    admin_delete_note,
    force_sensitive,
    invalidate_user_sessions,
    log_action,
    silence_actor,
    suspend_actor,
    unsilence_actor,
    unsuspend_actor,
)
from tests.conftest import make_note


async def test_log_action(db, test_user):
    """log_action creates a ModerationLog entry with the correct fields."""
    entry = await log_action(
        db, test_user, "test_action", "user", str(test_user.id), reason="test reason"
    )
    assert entry.id is not None
    assert entry.moderator_id == test_user.id
    assert entry.action == "test_action"
    assert entry.target_type == "user"
    assert entry.target_id == str(test_user.id)
    assert entry.reason == "test reason"
    assert entry.created_at is not None


@patch("app.services.delivery_service.enqueue_delivery", new_callable=AsyncMock)
@patch("app.services.follow_service.get_follower_inboxes", new_callable=AsyncMock, return_value=[])
async def test_suspend_actor(mock_inboxes, mock_delivery, db, mock_valkey, test_user, test_user_b):
    """Suspending an actor sets suspended_at and creates a moderation log."""
    actor = test_user_b.actor
    assert actor.suspended_at is None

    # invalidate_user_sessionsがvalkey.scanを呼ぶのでモック設定
    mock_valkey.scan = AsyncMock(return_value=(0, []))
    await suspend_actor(db, actor, test_user, reason="spam")
    assert actor.suspended_at is not None
    assert actor.is_suspended


@patch("app.services.delivery_service.enqueue_delivery", new_callable=AsyncMock)
@patch("app.services.follow_service.get_follower_inboxes", new_callable=AsyncMock, return_value=[])
async def test_unsuspend_actor(
    mock_inboxes, mock_delivery, db, mock_valkey, test_user, test_user_b,
):
    """Unsuspending a suspended actor clears suspended_at."""
    actor = test_user_b.actor
    mock_valkey.scan = AsyncMock(return_value=(0, []))
    await suspend_actor(db, actor, test_user, reason="spam")
    assert actor.is_suspended

    await unsuspend_actor(db, actor, test_user)
    assert actor.suspended_at is None
    assert not actor.is_suspended


async def test_silence_actor(db, test_user, test_user_b):
    """Silencing an actor sets silenced_at."""
    actor = test_user_b.actor
    assert actor.silenced_at is None

    await silence_actor(db, actor, test_user, reason="harassment")
    assert actor.silenced_at is not None
    assert actor.is_silenced


async def test_unsilence_actor(db, test_user, test_user_b):
    """Unsilencing a silenced actor clears silenced_at."""
    actor = test_user_b.actor
    await silence_actor(db, actor, test_user, reason="harassment")
    assert actor.is_silenced

    await unsilence_actor(db, actor, test_user)
    assert actor.silenced_at is None
    assert not actor.is_silenced


@patch("app.services.delivery_service.enqueue_delivery", new_callable=AsyncMock)
@patch("app.services.follow_service.get_follower_inboxes", new_callable=AsyncMock, return_value=[])
async def test_admin_delete_note(mock_inboxes, mock_delivery, db, test_user, test_user_b):
    """Admin-deleting a note sets deleted_at and creates a moderation log."""
    note = await make_note(db, test_user_b.actor, content="bad post")
    assert note.deleted_at is None

    await admin_delete_note(db, note, test_user, reason="TOS violation")
    assert note.deleted_at is not None


async def test_force_sensitive(db, test_user, test_user_b):
    """force_sensitive marks a note as sensitive."""
    note = await make_note(db, test_user_b.actor, content="nsfw content")
    assert note.sensitive is False

    await force_sensitive(db, note, test_user)
    assert note.sensitive is True


async def test_invalidate_user_sessions(mock_valkey, test_user):
    """invalidate_user_sessions scans for session keys and deletes matching ones."""
    user_id = test_user.id
    user_id_str = str(user_id)

    # セッションキーをスキャンして返す (decode_responses=Trueなのでstr)
    mock_valkey.scan = AsyncMock(side_effect=[
        (0, ["session:sess1", "session:sess2"]),
    ])
    # 各セッションキーのget呼び出しでユーザーIDを返す
    mock_valkey.get = AsyncMock(return_value=user_id_str)
    mock_valkey.delete = AsyncMock(return_value=1)
    mock_valkey.sadd = AsyncMock(return_value=1)
    mock_valkey.srem = AsyncMock(return_value=1)

    deleted = await invalidate_user_sessions(user_id)
    assert deleted == 2
    # セッションキーが削除されたことを確認
    assert mock_valkey.delete.call_count >= 2
