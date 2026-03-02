"""Handle incoming Create activities (mainly Create Note)."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.note import Note
from app.services.actor_service import fetch_remote_actor, get_actor_by_ap_id
from app.services.note_service import get_note_by_ap_id
from app.utils.sanitize import sanitize_html

logger = logging.getLogger(__name__)


async def handle_create(db: AsyncSession, activity: dict):
    obj = activity.get("object")
    if isinstance(obj, str):
        # Object is a reference, skip for now (would need to fetch)
        logger.info("Create with object reference, skipping: %s", obj)
        return

    if not isinstance(obj, dict):
        return

    obj_type = obj.get("type")
    if obj_type == "Note":
        await handle_create_note(db, activity, obj)
    else:
        logger.info("Unhandled Create object type: %s", obj_type)


async def handle_create_note(db: AsyncSession, activity: dict, note_data: dict):
    ap_id = note_data.get("id")
    if not ap_id:
        return

    # Skip if already exists
    existing = await get_note_by_ap_id(db, ap_id)
    if existing:
        return

    actor_ap_id = note_data.get("attributedTo") or activity.get("actor")
    if not actor_ap_id:
        return

    # Resolve actor
    actor = await get_actor_by_ap_id(db, actor_ap_id)
    if not actor:
        actor = await fetch_remote_actor(db, actor_ap_id)
    if not actor:
        logger.warning("Could not resolve actor %s for note %s", actor_ap_id, ap_id)
        return

    content = sanitize_html(note_data.get("content", ""))
    source_data = note_data.get("source")
    source = None
    if isinstance(source_data, dict):
        source = source_data.get("content")

    # Determine visibility
    to_list = note_data.get("to", [])
    cc_list = note_data.get("cc", [])
    public = "https://www.w3.org/ns/activitystreams#Public"

    if public in to_list:
        visibility = "public"
    elif public in cc_list:
        visibility = "unlisted"
    elif any(url.endswith("/followers") for url in to_list):
        visibility = "followers"
    else:
        visibility = "direct"

    # Resolve reply
    in_reply_to_ap_id = note_data.get("inReplyTo")
    in_reply_to_id = None
    if in_reply_to_ap_id:
        reply_note = await get_note_by_ap_id(db, in_reply_to_ap_id)
        if reply_note:
            in_reply_to_id = reply_note.id

    note = Note(
        ap_id=ap_id,
        actor_id=actor.id,
        content=content,
        source=source,
        visibility=visibility,
        sensitive=note_data.get("sensitive", False),
        spoiler_text=note_data.get("summary"),
        to=to_list,
        cc=cc_list,
        in_reply_to_id=in_reply_to_id,
        in_reply_to_ap_id=in_reply_to_ap_id,
        local=False,
    )

    published = note_data.get("published")
    if published:
        from datetime import datetime

        try:
            note.published = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            pass

    db.add(note)
    await db.commit()
    logger.info("Saved remote note %s from %s", ap_id, actor_ap_id)
