"""Handle Follow/Accept/Reject activities."""

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

    # Resolve follower (remote actor)
    follower = await get_actor_by_ap_id(db, actor_ap_id)
    if not follower:
        follower = await fetch_remote_actor(db, actor_ap_id)
    if not follower:
        logger.warning("Could not resolve follower actor %s", actor_ap_id)
        return

    # Resolve target (should be local)
    target = await get_actor_by_ap_id(db, target_ap_id)
    if not target or not target.is_local:
        logger.info("Follow target %s is not a local actor", target_ap_id)
        return

    # Check existing follow
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

    # Auto-accept if not manually approving
    if not target.manually_approves_followers:
        from app.activitypub.renderer import render_accept_activity
        from app.services.delivery_service import enqueue_delivery

        accept_id = f"{settings.server_url}/activities/{uuid.uuid4()}"
        # Use dynamic URL for local actor to ensure correct scheme
        actor_ap_id = f"{settings.server_url}/users/{target.username}"
        accept = render_accept_activity(accept_id, actor_ap_id, activity)

        await enqueue_delivery(db, target.id, follower.inbox_url, accept)
        logger.info("Auto-accepted follow from %s to %s", actor_ap_id, target_ap_id)


async def handle_accept(db: AsyncSession, activity: dict):
    """Handle Accept(Follow) -- remote server accepted our follow request."""
    inner = activity.get("object")
    if not isinstance(inner, dict):
        return

    if inner.get("type") != "Follow":
        return

    actor_ap_id = inner.get("actor")
    target_ap_id = inner.get("object")

    if not actor_ap_id or not target_ap_id:
        return

    follower = await get_actor_by_ap_id(db, actor_ap_id)
    target = await get_actor_by_ap_id(db, target_ap_id)

    if not follower or not target:
        return

    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == follower.id,
            Follow.following_id == target.id,
        )
    )
    follow = result.scalar_one_or_none()
    if follow:
        follow.accepted = True
        await db.commit()
        logger.info("Follow accepted: %s -> %s", actor_ap_id, target_ap_id)


async def handle_reject(db: AsyncSession, activity: dict):
    """Handle Reject(Follow) -- remote server rejected our follow request."""
    inner = activity.get("object")
    if not isinstance(inner, dict):
        return

    if inner.get("type") != "Follow":
        return

    actor_ap_id = inner.get("actor")
    target_ap_id = inner.get("object")

    if not actor_ap_id or not target_ap_id:
        return

    follower = await get_actor_by_ap_id(db, actor_ap_id)
    target = await get_actor_by_ap_id(db, target_ap_id)

    if not follower or not target:
        return

    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == follower.id,
            Follow.following_id == target.id,
        )
    )
    follow = result.scalar_one_or_none()
    if follow:
        await db.delete(follow)
        await db.commit()
        logger.info("Follow rejected: %s -> %s", actor_ap_id, target_ap_id)
