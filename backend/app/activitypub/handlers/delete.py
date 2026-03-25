"""Handle Delete activities."""

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.actor_service import get_actor_by_ap_id
from app.services.note_service import get_note_by_ap_id

logger = logging.getLogger(__name__)


async def handle_delete(db: AsyncSession, activity: dict):
    actor_ap_id = activity.get("actor")
    obj = activity.get("object")

    if not actor_ap_id:
        return

    # Object can be a string (ID) or a Tombstone dict
    if isinstance(obj, dict):
        object_id = obj.get("id")
    elif isinstance(obj, str):
        object_id = obj
    else:
        return

    if not object_id:
        return

    # Verify the actor owns the object
    actor = await get_actor_by_ap_id(db, actor_ap_id)
    if not actor:
        return

    note = await get_note_by_ap_id(db, object_id)
    if not note:
        return

    if note.actor_id != actor.id:
        logger.warning("Delete denied: actor %s does not own note %s", actor_ap_id, object_id)
        return

    note.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info("Deleted note %s by %s", object_id, actor_ap_id)

    # Remove from search index
    if settings.neko_search_enabled:
        from app.services.search_queue import enqueue_delete

        await enqueue_delete(note.id)
