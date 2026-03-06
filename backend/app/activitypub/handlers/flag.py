"""Handle incoming Flag (report) activities."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.actor_service import fetch_remote_actor, get_actor_by_ap_id
from app.services.note_service import get_note_by_ap_id

logger = logging.getLogger(__name__)


async def handle_flag(db: AsyncSession, activity: dict):
    """Handle Flag activity -- creates a report from a remote server."""
    actor_ap_id = activity.get("actor")
    if not actor_ap_id:
        return

    # Resolve reporting actor
    reporter = await get_actor_by_ap_id(db, actor_ap_id)
    if not reporter:
        reporter = await fetch_remote_actor(db, actor_ap_id)
    if not reporter:
        logger.warning("Could not resolve reporter actor %s", actor_ap_id)
        return

    # Determine target(s)
    obj = activity.get("object")
    target_ap_ids = []
    if isinstance(obj, str):
        target_ap_ids = [obj]
    elif isinstance(obj, list):
        target_ap_ids = [o for o in obj if isinstance(o, str)]

    if not target_ap_ids:
        return

    # First target should be the actor being reported
    target_actor = await get_actor_by_ap_id(db, target_ap_ids[0])
    if not target_actor:
        logger.info("Flag target actor not found: %s", target_ap_ids[0])
        return

    # Check if any remaining targets are notes
    target_note = None
    for ap_id in target_ap_ids[1:]:
        note = await get_note_by_ap_id(db, ap_id)
        if note:
            target_note = note
            break

    comment = activity.get("content", "")

    from app.services.report_service import create_report

    await create_report(
        db,
        reporter_actor=reporter,
        target_actor=target_actor,
        target_note=target_note,
        comment=comment,
        ap_id=activity.get("id"),
    )
    await db.commit()

    logger.info("Report received from %s about %s", actor_ap_id, target_ap_ids[0])
