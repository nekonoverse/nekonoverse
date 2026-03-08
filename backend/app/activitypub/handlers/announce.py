"""Handle Announce activities (boost/renote)."""

import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.note import Note
from app.services.actor_service import fetch_remote_actor, get_actor_by_ap_id
from app.services.note_service import fetch_remote_note, get_note_by_ap_id

logger = logging.getLogger(__name__)


async def handle_announce(db: AsyncSession, activity: dict):
    actor_ap_id = activity.get("actor")
    if not actor_ap_id:
        return

    actor = await get_actor_by_ap_id(db, actor_ap_id)
    if not actor:
        actor = await fetch_remote_actor(db, actor_ap_id)
    if not actor:
        logger.warning("Could not resolve actor %s for Announce", actor_ap_id)
        return

    # Get the boosted note's AP ID
    obj = activity.get("object")
    if isinstance(obj, dict):
        note_ap_id = obj.get("id")
    elif isinstance(obj, str):
        note_ap_id = obj
    else:
        return

    if not note_ap_id:
        return

    # Check for duplicate
    activity_id = activity.get("id")
    if activity_id:
        existing = await get_note_by_ap_id(db, activity_id)
        if existing:
            return

    # Resolve the original note (ローカルに無ければリモートからfetch)
    original = await get_note_by_ap_id(db, note_ap_id)
    if not original:
        original = await fetch_remote_note(db, note_ap_id)

    # Determine visibility from to/cc
    to_list = activity.get("to", [])
    cc_list = activity.get("cc", [])
    public = "https://www.w3.org/ns/activitystreams#Public"

    if public in to_list:
        visibility = "public"
    elif public in cc_list:
        visibility = "unlisted"
    else:
        visibility = "followers"

    note = Note(
        ap_id=activity_id or f"{actor_ap_id}/announces/{note_ap_id}",
        actor_id=actor.id,
        content="",
        visibility=visibility,
        renote_of_id=original.id if original else None,
        renote_of_ap_id=note_ap_id,
        to=to_list,
        cc=cc_list,
        local=False,
    )

    published = activity.get("published")
    if published:
        try:
            note.published = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            pass

    db.add(note)

    # Increment renotes_count on original
    if original:
        original.renotes_count = original.renotes_count + 1

    await db.commit()
    logger.info("Saved remote Announce %s from %s", activity_id, actor_ap_id)
