"""受信した Block activity を処理する。"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.follow import Follow
from app.models.user_block import UserBlock
from app.services.actor_service import get_actor_by_ap_id

logger = logging.getLogger(__name__)


async def handle_block(db: AsyncSession, activity: dict):
    """Block activity を処理する -- リモートアクターがローカルアクターをブロックする。"""
    actor_ap_id = activity.get("actor")
    target_ap_id = activity.get("object")

    if not actor_ap_id or not target_ap_id:
        return

    blocker = await get_actor_by_ap_id(db, actor_ap_id)
    target = await get_actor_by_ap_id(db, target_ap_id)

    if not blocker or not target:
        return

    # 既にブロック済みかチェック
    existing = await db.execute(
        select(UserBlock).where(
            UserBlock.actor_id == blocker.id,
            UserBlock.target_id == target.id,
        )
    )
    if existing.scalar_one_or_none():
        return

    block = UserBlock(actor_id=blocker.id, target_id=target.id)
    db.add(block)

    # 双方向のフォローを削除
    for follower_id, following_id in [
        (blocker.id, target.id),
        (target.id, blocker.id),
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

    await db.commit()
    logger.info("Block: %s -> %s", actor_ap_id, target_ap_id)
