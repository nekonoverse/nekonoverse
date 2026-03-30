"""アカウント削除サービス: 削除予約、キャンセル、実行。"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.actor import Actor
from app.models.bookmark import Bookmark
from app.models.drive_file import DriveFile
from app.models.follow import Follow
from app.models.note import Note
from app.models.notification import Notification
from app.models.oauth import OAuthToken
from app.models.pinned_note import PinnedNote
from app.models.push_subscription import PushSubscription
from app.models.reaction import Reaction
from app.models.user import User
from app.models.user_block import UserBlock
from app.models.user_mute import UserMute

logger = logging.getLogger(__name__)

GRACE_PERIOD_DAYS = 30


async def request_deletion(db: AsyncSession, user: User) -> datetime:
    """アカウント削除を予約する (30日間の猶予期間)。

    Returns:
        deletion_scheduled_at: 削除予定日時
    Raises:
        ValueError: 既に削除予約中 or 削除済み
    """
    actor = user.actor
    if not actor:
        raise ValueError("Actor not found")
    if actor.is_deleted:
        raise ValueError("Account is already deleted")
    if actor.is_deletion_pending:
        raise ValueError("Account deletion is already scheduled")

    now = datetime.now(timezone.utc)
    actor.deletion_scheduled_at = now + timedelta(days=GRACE_PERIOD_DAYS)
    actor.suspended_at = now
    await db.flush()

    logger.info("Account deletion scheduled for user %s (actor %s)", user.id, actor.id)
    return actor.deletion_scheduled_at


async def cancel_deletion(db: AsyncSession, user: User) -> None:
    """猶予期間中のアカウント削除をキャンセルする。

    Raises:
        ValueError: 削除予約されていない
    """
    actor = user.actor
    if not actor:
        raise ValueError("Actor not found")
    if not actor.is_deletion_pending:
        raise ValueError("Account deletion is not scheduled")

    actor.deletion_scheduled_at = None
    actor.suspended_at = None
    await db.flush()

    logger.info("Account deletion cancelled for user %s (actor %s)", user.id, actor.id)


async def execute_deletion(db: AsyncSession, actor: Actor) -> None:
    """アカウントの実際の削除を実行する。

    全関連データを削除し、Actor を Tombstone 化する。
    """
    now = datetime.now(timezone.utc)
    actor_id = actor.id
    user = actor.local_user

    # 1. 全ノートを論理削除
    await db.execute(
        update(Note)
        .where(Note.actor_id == actor_id, Note.deleted_at.is_(None))
        .values(deleted_at=now)
    )

    # 2. フォロワーに Delete(Person) を配送 (Follow レコード削除前に実行)
    if actor.is_local:
        await _deliver_delete_person(db, actor)

    # 3. フォロー関係のクリア + リモートへ Undo Follow 送信
    await _cleanup_follows(db, actor)

    # 4. リアクション削除
    await db.execute(delete(Reaction).where(Reaction.actor_id == actor_id))

    # 5. ブックマーク削除
    await db.execute(delete(Bookmark).where(Bookmark.actor_id == actor_id))

    # 6. 通知削除 (送信元・受信先)
    await db.execute(
        delete(Notification).where(
            (Notification.recipient_id == actor_id) | (Notification.sender_id == actor_id)
        )
    )

    # 7. ピン留め削除
    await db.execute(delete(PinnedNote).where(PinnedNote.actor_id == actor_id))

    # 8. ブロック/ミュート削除
    await db.execute(
        delete(UserBlock).where(
            (UserBlock.actor_id == actor_id) | (UserBlock.target_id == actor_id)
        )
    )
    await db.execute(
        delete(UserMute).where(
            (UserMute.actor_id == actor_id) | (UserMute.target_id == actor_id)
        )
    )

    # 9. プッシュ購読削除
    await db.execute(delete(PushSubscription).where(PushSubscription.actor_id == actor_id))

    # 10. OAuth トークン削除
    if user:
        await db.execute(delete(OAuthToken).where(OAuthToken.user_id == user.id))

    # 11. メディアファイル削除
    await _cleanup_media(db, actor, user)

    # 12. Actor プロフィールクリア + deleted_at 設定
    actor.display_name = None
    actor.summary = None
    actor.avatar_url = None
    actor.header_url = None
    actor.avatar_file_id = None
    actor.header_file_id = None
    actor.fields = None
    actor.is_cat = False
    actor.is_bot = False
    actor.discoverable = False
    actor.deleted_at = now
    actor.suspended_at = now
    actor.deletion_scheduled_at = None

    # 13. User の機密情報を無効化
    if user:
        user.email = f"deleted-{uuid.uuid4()}@deleted.invalid"
        user.password_hash = "!deleted"
        user.private_key_pem = ""
        user.is_active = False
        user.totp_secret = None
        user.totp_recovery_codes = None

    # 14. セッション無効化
    if user:
        from app.services.moderation_service import invalidate_user_sessions

        await invalidate_user_sessions(user.id)

    await db.flush()
    logger.info("Account deletion executed for actor %s", actor_id)


async def admin_force_delete(
    db: AsyncSession, actor: Actor, moderator: User, reason: str | None = None
) -> None:
    """管理者による即座のアカウント削除 (猶予期間なし)。"""
    await execute_deletion(db, actor)

    from app.services.moderation_service import log_action

    await log_action(db, moderator, "delete_account", "actor", str(actor.id), reason)


async def process_expired_deletions(db: AsyncSession) -> int:
    """猶予期間が経過したアカウントの削除を実行する。

    Returns:
        処理したアカウント数
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Actor)
        .options(selectinload(Actor.local_user))
        .where(
            Actor.deletion_scheduled_at.isnot(None),
            Actor.deletion_scheduled_at <= now,
            Actor.deleted_at.is_(None),
        )
    )
    actors = list(result.scalars().all())

    count = 0
    for actor in actors:
        try:
            await execute_deletion(db, actor)
            await db.commit()
            count += 1
            logger.info("Processed expired deletion for actor %s", actor.id)
        except Exception:
            await db.rollback()
            logger.exception("Failed to process deletion for actor %s", actor.id)

    return count


# ── Internal helpers ───────────────────────────────────────────


async def _cleanup_follows(db: AsyncSession, actor: Actor) -> None:
    """フォロー関係をクリアし、リモートに Undo(Follow) を送信する。"""
    # ローカルアクターの場合: 自分がフォローしているリモートアクターに Undo を送信
    if actor.is_local:
        outgoing_follows = await db.execute(
            select(Follow)
            .options(selectinload(Follow.following))
            .where(Follow.follower_id == actor.id)
        )
        for follow in outgoing_follows.scalars().all():
            target = follow.following
            if target and not target.is_local and target.inbox_url:
                await _send_undo_follow(db, actor, target, follow)

    # 全フォロー関係を削除
    await db.execute(
        delete(Follow).where(
            (Follow.follower_id == actor.id) | (Follow.following_id == actor.id)
        )
    )


async def _send_undo_follow(
    db: AsyncSession, actor: Actor, target: Actor, follow: Follow
) -> None:
    """リモートアクターに Undo(Follow) を送信する。"""
    from app.activitypub.renderer import render_follow_activity, render_undo_activity
    from app.services.actor_service import actor_uri
    from app.services.delivery_service import enqueue_delivery

    actor_url = actor_uri(actor)
    follow_ap_id = follow.ap_id or f"{settings.server_url}/activities/{uuid.uuid4()}"
    follow_activity = render_follow_activity(follow_ap_id, actor_url, target.ap_id)
    undo_id = f"{settings.server_url}/activities/{uuid.uuid4()}"
    undo_activity = render_undo_activity(undo_id, actor_url, follow_activity)
    await enqueue_delivery(db, actor.id, target.inbox_url, undo_activity)


async def _cleanup_media(db: AsyncSession, actor: Actor, user: User | None) -> None:
    """メディアファイルを削除する (S3 + DB)。"""
    if not user:
        return

    from app.storage import delete_file

    # avatar/header FK を先にクリア (FK 制約回避)
    actor.avatar_file_id = None
    actor.header_file_id = None
    await db.flush()

    # ユーザーが所有する全ファイルを削除
    result = await db.execute(
        select(DriveFile).where(DriveFile.owner_id == user.id)
    )
    files = list(result.scalars().all())
    for f in files:
        try:
            await delete_file(f.s3_key)
        except Exception:
            logger.warning("Failed to delete S3 object %s", f.s3_key)
        await db.delete(f)
    await db.flush()


async def _deliver_delete_person(db: AsyncSession, actor: Actor) -> None:
    """フォロワーに Delete(Person) Activity を配送する。"""
    from app.activitypub.renderer import render_delete_activity
    from app.services.actor_service import actor_uri
    from app.services.delivery_service import enqueue_delivery
    from app.services.follow_service import get_follower_inboxes

    actor_url = actor_uri(actor)
    delete_activity = render_delete_activity(
        activity_id=f"{actor_url}#delete",
        actor_ap_id=actor_url,
        object_id=actor_url,
    )
    inboxes = await get_follower_inboxes(db, actor.id)
    for inbox_url in inboxes:
        await enqueue_delivery(db, actor.id, inbox_url, delete_activity)
