"""ユーザーミュートサービス: ミュート、ミュート解除、確認、一覧。ローカル専用、AP配送なし。"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.actor import Actor
from app.models.user import User
from app.models.user_mute import UserMute


async def mute_actor(
    db: AsyncSession,
    user: User,
    target_actor: Actor,
    expires_at: datetime | None = None,
) -> UserMute:
    actor = user.actor

    existing = await db.execute(
        select(UserMute).where(
            UserMute.actor_id == actor.id,
            UserMute.target_id == target_actor.id,
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("Already muting")

    mute = UserMute(
        actor_id=actor.id,
        target_id=target_actor.id,
        expires_at=expires_at,
    )
    db.add(mute)
    await db.flush()
    return mute


async def unmute_actor(db: AsyncSession, user: User, target_actor: Actor) -> None:
    actor = user.actor

    result = await db.execute(
        select(UserMute).where(
            UserMute.actor_id == actor.id,
            UserMute.target_id == target_actor.id,
        )
    )
    mute = result.scalar_one_or_none()
    if not mute:
        raise ValueError("Not muting")

    await db.delete(mute)
    await db.flush()


async def get_muted_ids(db: AsyncSession, actor_id: uuid.UUID) -> list[uuid.UUID]:
    from datetime import timezone

    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(UserMute.target_id).where(
            UserMute.actor_id == actor_id,
            # 期限切れミュートを除外
            (UserMute.expires_at.is_(None)) | (UserMute.expires_at > now),
        )
    )
    return [row[0] for row in result.all()]


async def is_muting(db: AsyncSession, actor_id: uuid.UUID, target_id: uuid.UUID) -> bool:
    from datetime import timezone

    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(UserMute.id).where(
            UserMute.actor_id == actor_id,
            UserMute.target_id == target_id,
            (UserMute.expires_at.is_(None)) | (UserMute.expires_at > now),
        )
    )
    return result.scalar_one_or_none() is not None
