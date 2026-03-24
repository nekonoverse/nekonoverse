"""Service for managing proxy subscriptions via the system.proxy account.

The proxy account follows remote actors on behalf of local users (e.g. for list
subscriptions) so that the local server receives their public/unlisted posts
even when no real user follows them.
"""

import logging
import uuid

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.actor import Actor
from app.models.follow import Follow
from app.models.user import User
from app.services.system_account_service import get_proxy_actor

logger = logging.getLogger(__name__)


async def get_proxy_account(db: AsyncSession) -> User | None:
    """Return the system.proxy User (convenience wrapper)."""
    return await get_proxy_actor(db)


async def proxy_subscribe(db: AsyncSession, target_actor: Actor) -> Follow | None:
    """Make the proxy account follow a remote actor.

    Returns the Follow record, or None if the proxy account does not exist
    or the target is local.
    """
    if target_actor.is_local:
        logger.warning("proxy_subscribe called for local actor %s", target_actor.username)
        return None

    proxy_user = await get_proxy_actor(db)
    if not proxy_user:
        logger.error("system.proxy account not found")
        return None

    proxy_actor = proxy_user.actor

    # 既にフォロー済みならそのまま返す
    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == proxy_actor.id,
            Follow.following_id == target_actor.id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    from app.activitypub.renderer import render_follow_activity
    from app.config import settings
    from app.services.actor_service import actor_uri
    from app.services.delivery_service import enqueue_delivery

    follow_id = uuid.uuid4()
    ap_id = f"{settings.server_url}/activities/{follow_id}"

    follow = Follow(
        id=follow_id,
        ap_id=ap_id,
        follower_id=proxy_actor.id,
        following_id=target_actor.id,
        accepted=False,
    )
    db.add(follow)
    await db.commit()

    # リモートサーバーにFollow Activityを送信
    activity = render_follow_activity(ap_id, actor_uri(proxy_actor), target_actor.ap_id)
    await enqueue_delivery(db, proxy_actor.id, target_actor.inbox_url, activity)

    logger.info("Proxy subscribed to %s", target_actor.ap_id)
    return follow


async def proxy_unsubscribe(db: AsyncSession, target_actor: Actor) -> bool:
    """Make the proxy account unfollow a remote actor.

    Returns True if the follow was removed, False otherwise.
    """
    proxy_user = await get_proxy_actor(db)
    if not proxy_user:
        logger.error("system.proxy account not found")
        return False

    proxy_actor = proxy_user.actor

    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == proxy_actor.id,
            Follow.following_id == target_actor.id,
        )
    )
    follow = result.scalar_one_or_none()
    if not follow:
        return False

    await db.delete(follow)
    await db.commit()

    # リモートサーバーにUndo(Follow)を送信
    from app.activitypub.renderer import render_follow_activity, render_undo_activity
    from app.config import settings
    from app.services.actor_service import actor_uri
    from app.services.delivery_service import enqueue_delivery

    follow_activity = render_follow_activity(
        follow.ap_id or f"{settings.server_url}/activities/{uuid.uuid4()}",
        actor_uri(proxy_actor),
        target_actor.ap_id,
    )
    undo_id = f"{settings.server_url}/activities/{uuid.uuid4()}"
    undo_activity = render_undo_activity(undo_id, actor_uri(proxy_actor), follow_activity)
    await enqueue_delivery(db, proxy_actor.id, target_actor.inbox_url, undo_activity)

    logger.info("Proxy unsubscribed from %s", target_actor.ap_id)
    return True


async def is_proxy_subscribed(db: AsyncSession, target_actor_id: uuid.UUID) -> bool:
    """Check if the proxy account is following the given actor."""
    proxy_user = await get_proxy_actor(db)
    if not proxy_user:
        return False

    result = await db.execute(
        select(
            exists().where(
                Follow.follower_id == proxy_user.actor.id,
                Follow.following_id == target_actor_id,
            )
        )
    )
    return result.scalar() or False


_system_actor_ids_cache: set[uuid.UUID] | None = None
_system_actor_ids_cached_at: float = 0
_SYSTEM_IDS_TTL = 300  # 5 minutes


async def get_system_actor_ids(db: AsyncSession) -> set[uuid.UUID]:
    """Return the set of actor IDs belonging to system accounts (cached)."""
    import time

    global _system_actor_ids_cache, _system_actor_ids_cached_at
    now = time.monotonic()
    if _system_actor_ids_cache is not None and now - _system_actor_ids_cached_at < _SYSTEM_IDS_TTL:
        return _system_actor_ids_cache
    result = await db.execute(select(User.actor_id).where(User.is_system.is_(True)))
    _system_actor_ids_cache = set(result.scalars().all())
    _system_actor_ids_cached_at = now
    return _system_actor_ids_cache


async def has_real_local_follower(db: AsyncSession, remote_actor_id: uuid.UUID) -> bool:
    """Check if any non-system local user follows the given remote actor.

    Returns True if at least one real (non-system) local user has an accepted
    follow relationship with the remote actor.
    """
    result = await db.execute(
        select(
            exists(
                select(Follow.id)
                .join(Actor, Follow.follower_id == Actor.id)
                .join(User, Actor.id == User.actor_id)
                .where(
                    Follow.following_id == remote_actor_id,
                    Follow.accepted.is_(True),
                    Actor.domain.is_(None),
                    User.is_system.is_(False),
                )
            )
        )
    )
    return result.scalar() or False
