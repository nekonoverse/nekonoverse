"""ユーザーブロックサービス: ブロック、ブロック解除、確認、一覧。"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.actor import Actor
from app.models.follow import Follow
from app.models.user import User
from app.models.user_block import UserBlock
from app.services.actor_service import actor_uri


async def block_actor(db: AsyncSession, user: User, target_actor: Actor) -> UserBlock:
    actor = user.actor

    # 既にブロック済みか確認
    existing = await db.execute(
        select(UserBlock).where(
            UserBlock.actor_id == actor.id,
            UserBlock.target_id == target_actor.id,
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("Already blocking")

    block = UserBlock(actor_id=actor.id, target_id=target_actor.id)
    db.add(block)

    # 双方向のフォローを削除
    for follower_id, following_id in [
        (actor.id, target_actor.id),
        (target_actor.id, actor.id),
    ]:
        result = await db.execute(
            select(Follow).where(
                Follow.follower_id == follower_id,
                Follow.following_id == following_id,
            )
        )
        follow = result.scalar_one_or_none()
        if follow:
            await db.delete(follow)

    await db.flush()

    # リモートにBlock Activityを配送
    if not target_actor.is_local:
        from app.activitypub.renderer import render_block_activity
        from app.config import settings
        from app.services.delivery_service import enqueue_delivery

        activity_id = f"{settings.server_url}/activities/{uuid.uuid4()}"
        activity = render_block_activity(activity_id, actor_uri(actor), target_actor.ap_id)
        await enqueue_delivery(db, actor.id, target_actor.inbox_url, activity)

    return block


async def unblock_actor(db: AsyncSession, user: User, target_actor: Actor) -> None:
    actor = user.actor

    result = await db.execute(
        select(UserBlock).where(
            UserBlock.actor_id == actor.id,
            UserBlock.target_id == target_actor.id,
        )
    )
    block = result.scalar_one_or_none()
    if not block:
        raise ValueError("Not blocking")

    await db.delete(block)
    await db.flush()

    # リモートにUndo(Block)を配送
    if not target_actor.is_local:
        from app.activitypub.renderer import render_block_activity, render_undo_activity
        from app.config import settings
        from app.services.delivery_service import enqueue_delivery

        block_activity = render_block_activity(
            f"{settings.server_url}/activities/{uuid.uuid4()}",
            actor_uri(actor),
            target_actor.ap_id,
        )
        undo_id = f"{settings.server_url}/activities/{uuid.uuid4()}"
        undo_activity = render_undo_activity(undo_id, actor_uri(actor), block_activity)
        await enqueue_delivery(db, actor.id, target_actor.inbox_url, undo_activity)


async def get_blocked_ids(db: AsyncSession, actor_id: uuid.UUID) -> list[uuid.UUID]:
    result = await db.execute(select(UserBlock.target_id).where(UserBlock.actor_id == actor_id))
    return [row[0] for row in result.all()]


async def is_blocking(db: AsyncSession, actor_id: uuid.UUID, target_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(UserBlock.id).where(
            UserBlock.actor_id == actor_id,
            UserBlock.target_id == target_id,
        )
    )
    return result.scalar_one_or_none() is not None
