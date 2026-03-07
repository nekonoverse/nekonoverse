"""Handle incoming Move activities (account migration)."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.actor_service import fetch_remote_actor, get_actor_by_ap_id

logger = logging.getLogger(__name__)


async def handle_move(db: AsyncSession, activity: dict):
    actor_ap_id = activity.get("actor")
    target_ap_id = activity.get("target") or activity.get("object")

    if not actor_ap_id or not target_ap_id:
        logger.warning("Move activity missing actor or target")
        return

    # Verify actor == Move actor
    source_actor = await get_actor_by_ap_id(db, actor_ap_id)
    if not source_actor:
        source_actor = await fetch_remote_actor(db, actor_ap_id)
    if not source_actor:
        logger.warning("Could not resolve Move source: %s", actor_ap_id)
        return

    from app.services.move_service import handle_incoming_move

    await handle_incoming_move(db, source_actor, target_ap_id)
