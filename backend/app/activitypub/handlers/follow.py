"""Follow/Accept/Reject activity を処理する。"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.follow import Follow
from app.services.actor_service import fetch_remote_actor, get_actor_by_ap_id

logger = logging.getLogger(__name__)


async def handle_follow(db: AsyncSession, activity: dict):
    actor_ap_id = activity.get("actor")
    target_ap_id = activity.get("object")

    if not actor_ap_id or not target_ap_id:
        return

    # フォロワー (リモートアクター) を解決
    follower = await get_actor_by_ap_id(db, actor_ap_id)
    if not follower:
        follower = await fetch_remote_actor(db, actor_ap_id)
    if not follower:
        logger.warning("Could not resolve follower actor %s", actor_ap_id)
        return

    # ターゲットを解決 (ローカルであるべき)
    target = await get_actor_by_ap_id(db, target_ap_id)
    if not target or not target.is_local:
        logger.info("Follow target %s is not a local actor", target_ap_id)
        return

    # 既存のフォローをチェック
    existing = await db.execute(
        select(Follow).where(
            Follow.follower_id == follower.id,
            Follow.following_id == target.id,
        )
    )
    if existing.scalar_one_or_none():
        logger.info("Follow already exists: %s -> %s", actor_ap_id, target_ap_id)
    else:
        follow = Follow(
            ap_id=activity.get("id"),
            follower_id=follower.id,
            following_id=target.id,
            accepted=not target.manually_approves_followers,
        )
        db.add(follow)
        await db.commit()

        # 新しいフォロワーについてローカルのターゲットに通知
        from app.services.notification_service import create_notification, publish_notification

        notif_type = "follow" if not target.manually_approves_followers else "follow_request"
        notif = await create_notification(db, notif_type, target.id, follower.id)
        await db.commit()
        if notif:
            await publish_notification(notif)

    # 手動承認でない場合は自動承認
    if not target.manually_approves_followers:
        from app.activitypub.renderer import render_accept_activity
        from app.services.delivery_service import enqueue_delivery

        accept_id = f"{settings.server_url}/activities/{uuid.uuid4()}"
        # 正しいスキームを保証するためローカルアクターの動的 URL を使用
        actor_ap_id = f"{settings.server_url}/users/{target.username}"
        accept = render_accept_activity(accept_id, actor_ap_id, activity)

        await enqueue_delivery(db, target.id, follower.inbox_url, accept)
        logger.info("Auto-accepted follow from %s to %s", actor_ap_id, target_ap_id)


async def _resolve_follow_from_object(
    db: AsyncSession, activity: dict
) -> Follow | None:
    """Accept/Reject の object (dict または文字列 URI) から Follow レコードを解決する。"""
    accept_actor = activity.get("actor")
    inner = activity.get("object")

    if isinstance(inner, str):
        # object が Follow activity の URI 参照 (例: Mitra)
        if not accept_actor:
            logger.warning("Accept/Reject missing actor field for string object %s", inner)
            return None
        result = await db.execute(select(Follow).where(Follow.ap_id == inner))
        follow = result.scalar_one_or_none()
        if not follow:
            logger.warning("No follow found for ap_id %s", inner)
            return None
        # Accept/Reject の actor がフォローターゲットと一致するか検証
        target = await get_actor_by_ap_id(db, accept_actor)
        if not target or target.id != follow.following_id:
            logger.warning(
                "Accept/Reject actor mismatch: actor=%s does not match follow target",
                accept_actor,
            )
            return None
        return follow

    if not isinstance(inner, dict):
        return None

    if inner.get("type") != "Follow":
        return None

    # M-16: Accept actorがフォロー先(inner object)と一致するか検証
    target_ap_id = inner.get("object")
    if accept_actor and target_ap_id and accept_actor != target_ap_id:
        logger.warning(
            "Accept/Reject actor mismatch: actor=%s, follow.object=%s",
            accept_actor,
            target_ap_id,
        )
        return None

    actor_ap_id = inner.get("actor")
    if not actor_ap_id or not target_ap_id:
        return None

    follower = await get_actor_by_ap_id(db, actor_ap_id)
    target = await get_actor_by_ap_id(db, target_ap_id)
    if not follower or not target:
        return None

    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == follower.id,
            Follow.following_id == target.id,
        )
    )
    return result.scalar_one_or_none()


async def handle_accept(db: AsyncSession, activity: dict):
    """Accept(Follow) を処理する -- リモートサーバーがフォローリクエストを承認した。"""
    follow = await _resolve_follow_from_object(db, activity)
    if follow:
        follow.accepted = True
        await db.commit()
        logger.info("Follow accepted: follow.ap_id=%s", follow.ap_id)


async def handle_reject(db: AsyncSession, activity: dict):
    """Reject(Follow) を処理する -- リモートサーバーがフォローリクエストを拒否した。"""
    follow = await _resolve_follow_from_object(db, activity)
    if follow:
        await db.delete(follow)
        await db.commit()
        logger.info("Follow rejected: follow.ap_id=%s", follow.ap_id)
