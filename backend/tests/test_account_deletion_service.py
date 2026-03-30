"""アカウント削除サービスのユニットテスト。"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models.bookmark import Bookmark
from app.models.follow import Follow
from app.models.notification import Notification
from app.models.note import Note
from app.models.oauth import OAuthToken
from app.models.pinned_note import PinnedNote
from app.models.push_subscription import PushSubscription
from app.models.reaction import Reaction
from app.models.user_block import UserBlock
from app.models.user_mute import UserMute
from app.services.account_deletion_service import (
    GRACE_PERIOD_DAYS,
    admin_force_delete,
    cancel_deletion,
    execute_deletion,
    process_expired_deletions,
    request_deletion,
)

from tests.conftest import make_note, make_remote_actor


# ── request_deletion ──────────────────────────────────────────


async def test_request_deletion_sets_scheduled_at(db, test_user, mock_valkey):
    """削除予約で deletion_scheduled_at が now + 30日に設定される。"""
    before = datetime.now(timezone.utc)
    result = await request_deletion(db, test_user)
    after = datetime.now(timezone.utc)

    expected_min = before + timedelta(days=GRACE_PERIOD_DAYS)
    expected_max = after + timedelta(days=GRACE_PERIOD_DAYS)
    assert expected_min <= result <= expected_max

    await db.refresh(test_user.actor)
    assert test_user.actor.deletion_scheduled_at == result


async def test_request_deletion_suspends_account(db, test_user, mock_valkey):
    """削除予約でアカウントが凍結される。"""
    await request_deletion(db, test_user)
    await db.refresh(test_user.actor)
    assert test_user.actor.is_suspended


async def test_request_deletion_already_pending(db, test_user, mock_valkey):
    """既に削除予約中のアカウントは重複予約できない。"""
    await request_deletion(db, test_user)
    with pytest.raises(ValueError, match="already scheduled"):
        await request_deletion(db, test_user)


async def test_request_deletion_already_deleted(db, test_user, mock_valkey):
    """既に削除済みのアカウントには予約できない。"""
    test_user.actor.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    with pytest.raises(ValueError, match="already deleted"):
        await request_deletion(db, test_user)


# ── cancel_deletion ───────────────────────────────────────────


async def test_cancel_deletion_clears_scheduled_at(db, test_user, mock_valkey):
    """キャンセルで deletion_scheduled_at がクリアされる。"""
    await request_deletion(db, test_user)
    await cancel_deletion(db, test_user)

    await db.refresh(test_user.actor)
    assert test_user.actor.deletion_scheduled_at is None


async def test_cancel_deletion_unsuspends_account(db, test_user, mock_valkey):
    """キャンセルで凍結が解除される。"""
    await request_deletion(db, test_user)
    await cancel_deletion(db, test_user)

    await db.refresh(test_user.actor)
    assert not test_user.actor.is_suspended


async def test_cancel_deletion_not_pending(db, test_user, mock_valkey):
    """削除予約されていないアカウントのキャンセルはエラーになる。"""
    with pytest.raises(ValueError, match="not scheduled"):
        await cancel_deletion(db, test_user)


# ── execute_deletion ──────────────────────────────────────────


async def test_execute_deletion_soft_deletes_notes(db, test_user, mock_valkey):
    """実行で全ノートが論理削除される。"""
    note1 = await make_note(db, test_user.actor, content="Note 1")
    note2 = await make_note(db, test_user.actor, content="Note 2")

    with patch("app.services.account_deletion_service._deliver_delete_person", new_callable=AsyncMock):
        await execute_deletion(db, test_user.actor)

    await db.refresh(note1)
    await db.refresh(note2)
    assert note1.deleted_at is not None
    assert note2.deleted_at is not None


async def test_execute_deletion_clears_follows(db, test_user, test_user_b, mock_valkey):
    """実行で全フォロー関係がクリアされる。"""
    # test_user → test_user_b のフォロー
    follow = Follow(
        follower_id=test_user.actor_id,
        following_id=test_user_b.actor_id,
        accepted=True,
    )
    db.add(follow)
    # test_user_b → test_user のフォロー
    follow2 = Follow(
        follower_id=test_user_b.actor_id,
        following_id=test_user.actor_id,
        accepted=True,
    )
    db.add(follow2)
    await db.flush()

    with patch("app.services.account_deletion_service._deliver_delete_person", new_callable=AsyncMock):
        await execute_deletion(db, test_user.actor)

    result = await db.execute(
        select(Follow).where(
            (Follow.follower_id == test_user.actor_id)
            | (Follow.following_id == test_user.actor_id)
        )
    )
    assert result.scalars().all() == []


async def test_execute_deletion_sends_undo_follow_to_remote(db, test_user, mock_valkey):
    """フォローしているリモートアクターに Undo(Follow) が送信される。"""
    remote = await make_remote_actor(db, username="remote_del", domain="del.example")
    follow = Follow(
        follower_id=test_user.actor_id,
        following_id=remote.id,
        accepted=True,
    )
    db.add(follow)
    await db.flush()

    with (
        patch(
            "app.services.delivery_service.enqueue_delivery",
            new_callable=AsyncMock,
        ) as mock_deliver,
        patch(
            "app.services.account_deletion_service._deliver_delete_person",
            new_callable=AsyncMock,
        ),
    ):
        await execute_deletion(db, test_user.actor)

    # Undo(Follow) が送信されるはず
    assert mock_deliver.call_count >= 1
    # 最初の呼び出しは Undo(Follow)
    call_args = mock_deliver.call_args_list[0]
    payload = call_args[1].get("payload") or call_args[0][3]
    assert payload["type"] == "Undo"
    assert payload["object"]["type"] == "Follow"


async def test_execute_deletion_deletes_reactions(db, test_user, mock_valkey):
    """実行でリアクションが削除される。"""
    note = await make_note(db, test_user.actor, content="target")
    reaction = Reaction(
        actor_id=test_user.actor_id,
        note_id=note.id,
        emoji="👍",
    )
    db.add(reaction)
    await db.flush()

    with patch("app.services.account_deletion_service._deliver_delete_person", new_callable=AsyncMock):
        await execute_deletion(db, test_user.actor)

    result = await db.execute(
        select(Reaction).where(Reaction.actor_id == test_user.actor_id)
    )
    assert result.scalars().all() == []


async def test_execute_deletion_deletes_bookmarks(db, test_user, mock_valkey):
    """実行でブックマークが削除される。"""
    note = await make_note(db, test_user.actor, content="bookmarked")
    bookmark = Bookmark(actor_id=test_user.actor_id, note_id=note.id)
    db.add(bookmark)
    await db.flush()

    with patch("app.services.account_deletion_service._deliver_delete_person", new_callable=AsyncMock):
        await execute_deletion(db, test_user.actor)

    result = await db.execute(
        select(Bookmark).where(Bookmark.actor_id == test_user.actor_id)
    )
    assert result.scalars().all() == []


async def test_execute_deletion_deletes_notifications(db, test_user, test_user_b, mock_valkey):
    """実行で通知 (送信元・受信先) が削除される。"""
    # test_user が受信した通知
    notif1 = Notification(
        recipient_id=test_user.actor_id,
        sender_id=test_user_b.actor_id,
        type="follow",
    )
    # test_user が送信した通知
    notif2 = Notification(
        recipient_id=test_user_b.actor_id,
        sender_id=test_user.actor_id,
        type="follow",
    )
    db.add(notif1)
    db.add(notif2)
    await db.flush()

    with patch("app.services.account_deletion_service._deliver_delete_person", new_callable=AsyncMock):
        await execute_deletion(db, test_user.actor)

    result = await db.execute(
        select(Notification).where(
            (Notification.recipient_id == test_user.actor_id)
            | (Notification.sender_id == test_user.actor_id)
        )
    )
    assert result.scalars().all() == []


async def test_execute_deletion_deletes_pinned_notes(db, test_user, mock_valkey):
    """実行でピン留めノートが削除される。"""
    note = await make_note(db, test_user.actor, content="pinned")
    pin = PinnedNote(actor_id=test_user.actor_id, note_id=note.id)
    db.add(pin)
    await db.flush()

    with patch("app.services.account_deletion_service._deliver_delete_person", new_callable=AsyncMock):
        await execute_deletion(db, test_user.actor)

    result = await db.execute(
        select(PinnedNote).where(PinnedNote.actor_id == test_user.actor_id)
    )
    assert result.scalars().all() == []


async def test_execute_deletion_deletes_blocks_mutes(db, test_user, test_user_b, mock_valkey):
    """実行でユーザーブロック/ミュートが削除される。"""
    block = UserBlock(actor_id=test_user.actor_id, target_id=test_user_b.actor_id)
    mute = UserMute(actor_id=test_user.actor_id, target_id=test_user_b.actor_id)
    db.add(block)
    db.add(mute)
    await db.flush()

    with patch("app.services.account_deletion_service._deliver_delete_person", new_callable=AsyncMock):
        await execute_deletion(db, test_user.actor)

    result_b = await db.execute(
        select(UserBlock).where(
            (UserBlock.actor_id == test_user.actor_id)
            | (UserBlock.target_id == test_user.actor_id)
        )
    )
    assert result_b.scalars().all() == []

    result_m = await db.execute(
        select(UserMute).where(
            (UserMute.actor_id == test_user.actor_id)
            | (UserMute.target_id == test_user.actor_id)
        )
    )
    assert result_m.scalars().all() == []


async def test_execute_deletion_deletes_push_subscriptions(db, test_user, mock_valkey):
    """実行でプッシュサブスクリプションが削除される。"""
    sub = PushSubscription(
        actor_id=test_user.actor_id,
        session_id="test-push-session",
        endpoint="https://push.example/sub1",
        key_p256dh="test-key",
        key_auth="test-auth",
    )
    db.add(sub)
    await db.flush()

    with patch("app.services.account_deletion_service._deliver_delete_person", new_callable=AsyncMock):
        await execute_deletion(db, test_user.actor)

    result = await db.execute(
        select(PushSubscription).where(PushSubscription.actor_id == test_user.actor_id)
    )
    assert result.scalars().all() == []


async def test_execute_deletion_revokes_oauth_tokens(db, test_user, mock_valkey):
    """実行で OAuth トークンが削除される。"""
    from app.models.oauth import OAuthApplication

    oauth_app = OAuthApplication(
        name="test-app",
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uris="https://example.com/callback",
        scopes="read write",
    )
    db.add(oauth_app)
    await db.flush()

    token = OAuthToken(
        user_id=test_user.id,
        application_id=oauth_app.id,
        access_token="test-access-token",
        token_type="Bearer",
        scopes="read write",
    )
    db.add(token)
    await db.flush()

    with patch("app.services.account_deletion_service._deliver_delete_person", new_callable=AsyncMock):
        await execute_deletion(db, test_user.actor)

    result = await db.execute(
        select(OAuthToken).where(OAuthToken.user_id == test_user.id)
    )
    assert result.scalars().all() == []


async def test_execute_deletion_scrubs_user_data(db, test_user, mock_valkey):
    """実行でメールアドレスとパスワードハッシュが無効化される。"""
    original_email = test_user.email

    with patch("app.services.account_deletion_service._deliver_delete_person", new_callable=AsyncMock):
        await execute_deletion(db, test_user.actor)

    await db.refresh(test_user)
    assert test_user.email != original_email
    assert test_user.email.endswith("@deleted.invalid")
    assert test_user.password_hash == "!deleted"
    assert test_user.private_key_pem == ""
    assert test_user.is_active is False


async def test_execute_deletion_clears_actor_profile(db, test_user, mock_valkey):
    """実行で Actor のプロフィール情報がクリアされる。"""
    test_user.actor.display_name = "Will Be Cleared"
    test_user.actor.summary = "This should go away"
    await db.flush()

    with patch("app.services.account_deletion_service._deliver_delete_person", new_callable=AsyncMock):
        await execute_deletion(db, test_user.actor)

    await db.refresh(test_user.actor)
    assert test_user.actor.display_name is None
    assert test_user.actor.summary is None
    assert test_user.actor.avatar_url is None
    assert test_user.actor.header_url is None
    assert test_user.actor.fields is None


async def test_execute_deletion_sets_deleted_at(db, test_user, mock_valkey):
    """実行で Actor.deleted_at が設定される。"""
    with patch("app.services.account_deletion_service._deliver_delete_person", new_callable=AsyncMock):
        await execute_deletion(db, test_user.actor)

    await db.refresh(test_user.actor)
    assert test_user.actor.is_deleted


async def test_execute_deletion_sends_delete_person(db, test_user, test_user_b, mock_valkey):
    """フォロワーに Delete(Person) activity が配送される。"""
    remote = await make_remote_actor(db, username="follower_del", domain="fol.example")
    follow = Follow(
        follower_id=remote.id,
        following_id=test_user.actor_id,
        accepted=True,
    )
    db.add(follow)
    await db.flush()

    # フォローは _cleanup_follows で削除されるため、
    # get_follower_inboxes をモックして inbox を返す
    with (
        patch(
            "app.services.delivery_service.enqueue_delivery",
            new_callable=AsyncMock,
        ) as mock_deliver,
        patch(
            "app.services.follow_service.get_follower_inboxes",
            new_callable=AsyncMock,
            return_value=[remote.inbox_url],
        ),
    ):
        await execute_deletion(db, test_user.actor)

    # Delete(Person) が送信されるはず
    found_delete = False
    for call in mock_deliver.call_args_list:
        payload = call[1].get("payload") or call[0][3]
        if payload.get("type") == "Delete":
            found_delete = True
            assert payload["object"]["type"] == "Tombstone"
    assert found_delete, "Delete(Person) activity was not delivered"


async def test_execute_deletion_preserves_username(db, test_user, mock_valkey):
    """削除後も Actor.username と Actor.ap_id は保持される (再登録防止)。"""
    original_username = test_user.actor.username
    original_ap_id = test_user.actor.ap_id

    with patch("app.services.account_deletion_service._deliver_delete_person", new_callable=AsyncMock):
        await execute_deletion(db, test_user.actor)

    await db.refresh(test_user.actor)
    assert test_user.actor.username == original_username
    assert test_user.actor.ap_id == original_ap_id


async def test_execute_deletion_invalidates_sessions(db, test_user, mock_valkey):
    """実行で全セッションが無効化される。"""
    with (
        patch("app.services.account_deletion_service._deliver_delete_person", new_callable=AsyncMock),
        patch(
            "app.services.moderation_service.invalidate_user_sessions",
            new_callable=AsyncMock,
        ) as mock_invalidate,
    ):
        await execute_deletion(db, test_user.actor)

    mock_invalidate.assert_called_once_with(test_user.id)


async def test_execute_deletion_clears_deletion_scheduled_at(db, test_user, mock_valkey):
    """実行で deletion_scheduled_at がクリアされる��"""
    test_user.actor.deletion_scheduled_at = datetime.now(timezone.utc) - timedelta(days=1)
    await db.flush()

    with patch("app.services.account_deletion_service._deliver_delete_person", new_callable=AsyncMock):
        await execute_deletion(db, test_user.actor)

    await db.refresh(test_user.actor)
    assert test_user.actor.deletion_scheduled_at is None


# ── admin_force_delete ────────────────────────────────────────


async def test_admin_force_delete_immediate(db, test_user, test_user_b, mock_valkey):
    """管理者強制削除で猶予期間なしに即座に削除される。"""
    with (
        patch("app.services.account_deletion_service._deliver_delete_person", new_callable=AsyncMock),
        patch(
            "app.services.moderation_service.invalidate_user_sessions",
            new_callable=AsyncMock,
        ),
    ):
        await admin_force_delete(db, test_user.actor, test_user_b, reason="spam")

    await db.refresh(test_user.actor)
    assert test_user.actor.is_deleted


async def test_admin_force_delete_logs_action(db, test_user, test_user_b, mock_valkey):
    """管理者強制削除がモデレーションログに記録される。"""
    from app.models.moderation_log import ModerationLog

    with (
        patch("app.services.account_deletion_service._deliver_delete_person", new_callable=AsyncMock),
        patch(
            "app.services.moderation_service.invalidate_user_sessions",
            new_callable=AsyncMock,
        ),
    ):
        await admin_force_delete(db, test_user.actor, test_user_b, reason="policy violation")

    result = await db.execute(
        select(ModerationLog).where(
            ModerationLog.action == "delete_account",
            ModerationLog.target_id == str(test_user.actor.id),
        )
    )
    log = result.scalar_one_or_none()
    assert log is not None
    assert log.reason == "policy violation"
    assert log.moderator_id == test_user_b.id


# ── process_expired_deletions ────────────────────────────────


async def test_process_expired_deletions_executes(db, test_user, mock_valkey):
    """猶予期間が経過したアカウントが自動的に削除される。"""
    test_user.actor.deletion_scheduled_at = datetime.now(timezone.utc) - timedelta(hours=1)
    test_user.actor.suspended_at = datetime.now(timezone.utc) - timedelta(days=30)
    await db.flush()

    with (
        patch("app.services.account_deletion_service._deliver_delete_person", new_callable=AsyncMock),
        patch(
            "app.services.moderation_service.invalidate_user_sessions",
            new_callable=AsyncMock,
        ),
    ):
        count = await process_expired_deletions(db)

    assert count == 1
    await db.refresh(test_user.actor)
    assert test_user.actor.is_deleted


async def test_process_expired_deletions_skips_not_expired(db, test_user, mock_valkey):
    """猶予期間が経過していないアカウントはスキップされる。"""
    test_user.actor.deletion_scheduled_at = datetime.now(timezone.utc) + timedelta(days=15)
    test_user.actor.suspended_at = datetime.now(timezone.utc)
    await db.flush()

    count = await process_expired_deletions(db)
    assert count == 0
    await db.refresh(test_user.actor)
    assert not test_user.actor.is_deleted


async def test_process_expired_deletions_skips_already_deleted(db, test_user, mock_valkey):
    """既に deleted_at が設定されているアカウントはスキップされる。"""
    now = datetime.now(timezone.utc)
    test_user.actor.deletion_scheduled_at = now - timedelta(hours=1)
    test_user.actor.deleted_at = now - timedelta(hours=2)
    await db.flush()

    count = await process_expired_deletions(db)
    assert count == 0
