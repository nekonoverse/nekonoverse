"""Account migration service: Move activity handling."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.actor import Actor
from app.models.follow import Follow
from app.models.user import User

logger = logging.getLogger(__name__)


async def handle_incoming_move(
    db: AsyncSession,
    source_actor: Actor,
    target_ap_id: str,
) -> bool:
    """Handle a received Move activity: set movedTo, migrate followers."""
    from app.services.actor_service import fetch_remote_actor

    target_actor = await fetch_remote_actor(db, target_ap_id)
    if not target_actor:
        logger.warning("Move target %s not found", target_ap_id)
        return False

    # Verify alsoKnownAs on target includes source
    also_known = target_actor.also_known_as or []
    if source_actor.ap_id not in also_known:
        logger.warning(
            "Move rejected: target %s alsoKnownAs does not include source %s",
            target_ap_id,
            source_actor.ap_id,
        )
        return False

    # Mark source as moved
    source_actor.moved_to_ap_id = target_ap_id
    await db.flush()

    # Migrate local followers to target
    result = await db.execute(
        select(Follow).where(
            Follow.following_id == source_actor.id,
            Follow.accepted.is_(True),
        )
    )
    follows = list(result.scalars().all())

    for follow in follows:
        # Check if already following target
        existing = await db.execute(
            select(Follow).where(
                Follow.follower_id == follow.follower_id,
                Follow.following_id == target_actor.id,
            )
        )
        if existing.scalar_one_or_none():
            continue

        # Create new follow to target
        new_follow = Follow(
            follower_id=follow.follower_id,
            following_id=target_actor.id,
            accepted=True,
        )
        db.add(new_follow)

    await db.commit()
    logger.info("Processed Move from %s to %s, migrated %d followers",
                source_actor.ap_id, target_ap_id, len(follows))
    return True


async def initiate_move(
    db: AsyncSession,
    user: User,
    target_ap_id: str,
) -> bool:
    """Initiate an account move from the local user to a target."""
    from app.services.actor_service import fetch_remote_actor

    actor = user.actor

    # Verify the target actor has alsoKnownAs pointing back
    target_actor = await fetch_remote_actor(db, target_ap_id)
    if not target_actor:
        raise ValueError("Target actor not found")

    also_known = target_actor.also_known_as or []
    if actor.ap_id not in also_known:
        raise ValueError("Target actor's alsoKnownAs must include your AP ID")

    # Set movedTo on self
    actor.moved_to_ap_id = target_ap_id
    await db.flush()

    # Deliver Move activity to followers
    from app.activitypub.renderer import render_move_activity
    from app.services.delivery_service import enqueue_delivery
    from app.services.follow_service import get_follower_inboxes

    activity = render_move_activity(
        activity_id=f"{actor.ap_id}/move/{target_actor.id}",
        actor_ap_id=actor.ap_id,
        target_ap_id=target_ap_id,
    )
    inboxes = await get_follower_inboxes(db, actor.id)
    for inbox_url in inboxes:
        await enqueue_delivery(db, actor.id, inbox_url, activity)

    await db.commit()
    return True
