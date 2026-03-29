"""アカウント移行サービス: Move Activity の処理。"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.actor import Actor
from app.models.follow import Follow
from app.models.user import User

logger = logging.getLogger(__name__)


async def handle_incoming_move(
    db: AsyncSession,
    source_actor: Actor,
    target_ap_id: str,
) -> bool:
    """受信した Move Activity を処理する: movedTo を設定し、フォロワーを移行する。

    ローカルフォロワーには move 通知を作成し、移行先がリモートの場合は
    ローカルフォロワーから Follow Activity を配送する。
    """
    from app.services.actor_service import fetch_remote_actor

    target_actor = await fetch_remote_actor(db, target_ap_id)
    if not target_actor:
        logger.warning("Move target %s not found", target_ap_id)
        return False

    # 移行先の alsoKnownAs に移行元が含まれているか検証
    also_known = target_actor.also_known_as or []
    if source_actor.ap_id not in also_known:
        logger.warning(
            "Move rejected: target %s alsoKnownAs does not include source %s",
            target_ap_id,
            source_actor.ap_id,
        )
        return False

    # 移行元を移行済みとしてマーク
    source_actor.moved_to_ap_id = target_ap_id
    await db.flush()

    # ローカルフォロワーを移行先に移行
    result = await db.execute(
        select(Follow)
        .where(
            Follow.following_id == source_actor.id,
            Follow.accepted.is_(True),
        )
        .options(selectinload(Follow.follower))
    )
    follows = list(result.scalars().all())

    migrated = 0
    for follow in follows:
        follower_actor = follow.follower
        if not follower_actor:
            continue

        # 既に移行先をフォロー済みか確認
        existing = await db.execute(
            select(Follow).where(
                Follow.follower_id == follow.follower_id,
                Follow.following_id == target_actor.id,
            )
        )
        if existing.scalar_one_or_none():
            # 既にフォロー済みでも通知は送る
            await _notify_move(db, follower_actor, source_actor)
            continue

        # 移行先への新しいフォローを作成
        new_follow = Follow(
            follower_id=follow.follower_id,
            following_id=target_actor.id,
            accepted=not target_actor.is_local or True,
        )
        db.add(new_follow)
        migrated += 1

        # ローカルフォロワー → リモート移行先の場合、Follow Activity を配送
        if follower_actor.is_local and not target_actor.is_local and target_actor.inbox_url:
            await _send_follow_to_target(
                db, follower_actor, target_actor, new_follow
            )

        # ローカルフォロワーに move 通知を作成
        await _notify_move(db, follower_actor, source_actor)

    await db.commit()
    logger.info(
        "Processed Move from %s to %s, migrated %d/%d followers",
        source_actor.ap_id,
        target_ap_id,
        migrated,
        len(follows),
    )
    return True


async def _notify_move(
    db: AsyncSession,
    follower_actor: Actor,
    source_actor: Actor,
) -> None:
    """ローカルフォロワーに move 通知を作成する。"""
    if not follower_actor.is_local:
        return

    from app.services.notification_service import create_notification

    await create_notification(
        db,
        type="move",
        recipient_id=follower_actor.id,
        sender_id=source_actor.id,
    )


async def _send_follow_to_target(
    db: AsyncSession,
    follower_actor: Actor,
    target_actor: Actor,
    follow: Follow,
) -> None:
    """ローカルフォロワーから移行先リモートアクターへ Follow Activity を配送する。"""
    from app.activitypub.renderer import render_follow_activity
    from app.services.delivery_service import enqueue_delivery

    follow_id = f"{follower_actor.ap_id}#follows/{uuid.uuid4()}"
    activity = render_follow_activity(
        activity_id=follow_id,
        actor_ap_id=follower_actor.ap_id,
        target_ap_id=target_actor.ap_id,
    )
    await enqueue_delivery(db, follower_actor.id, target_actor.inbox_url, activity)


async def initiate_move(
    db: AsyncSession,
    user: User,
    target_ap_id: str,
) -> bool:
    """ローカルユーザーから移行先へのアカウント移行を開始する。"""
    from app.services.actor_service import fetch_remote_actor

    actor = user.actor

    # 移行先アクターの alsoKnownAs に自分が含まれているか検証
    target_actor = await fetch_remote_actor(db, target_ap_id)
    if not target_actor:
        raise ValueError("Target actor not found")

    from app.services.actor_service import actor_uri

    also_known = target_actor.also_known_as or []
    actor_url = actor_uri(actor)
    if actor_url not in also_known:
        raise ValueError("Target actor's alsoKnownAs must include your AP ID")

    # 自身に movedTo を設定
    actor.moved_to_ap_id = target_ap_id
    await db.flush()

    # フォロワーに Move Activity を配送
    from app.activitypub.renderer import render_move_activity
    from app.services.delivery_service import enqueue_delivery
    from app.services.follow_service import get_follower_inboxes

    activity = render_move_activity(
        activity_id=f"{actor_url}/move/{target_actor.id}",
        actor_ap_id=actor_url,
        target_ap_id=target_ap_id,
    )
    inboxes = await get_follower_inboxes(db, actor.id)
    for inbox_url in inboxes:
        await enqueue_delivery(db, actor.id, inbox_url, activity)

    await db.commit()
    return True
