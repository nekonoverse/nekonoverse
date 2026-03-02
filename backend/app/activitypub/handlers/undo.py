"""Handle Undo activities (Undo Follow, Undo Like, etc.)."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.follow import Follow
from app.models.reaction import Reaction
from app.services.actor_service import get_actor_by_ap_id
from app.services.note_service import get_note_by_ap_id

logger = logging.getLogger(__name__)


async def handle_undo(db: AsyncSession, activity: dict):
    inner = activity.get("object")
    if not isinstance(inner, dict):
        return

    inner_type = inner.get("type")
    if inner_type == "Follow":
        await _undo_follow(db, activity, inner)
    elif inner_type in ("Like", "EmojiReact"):
        await _undo_reaction(db, activity, inner)
    else:
        logger.info("Unhandled Undo inner type: %s", inner_type)


async def _undo_follow(db: AsyncSession, activity: dict, inner: dict):
    actor_ap_id = inner.get("actor") or activity.get("actor")
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
        logger.info("Undo follow: %s -> %s", actor_ap_id, target_ap_id)


async def _undo_reaction(db: AsyncSession, activity: dict, inner: dict):
    actor_ap_id = inner.get("actor") or activity.get("actor")
    note_ap_id = inner.get("object")

    if not actor_ap_id or not note_ap_id:
        return

    actor = await get_actor_by_ap_id(db, actor_ap_id)
    if not actor:
        return

    note = await get_note_by_ap_id(db, note_ap_id)
    if not note:
        return

    # Find reaction by ap_id or actor+note
    inner_id = inner.get("id")
    if inner_id:
        result = await db.execute(select(Reaction).where(Reaction.ap_id == inner_id))
    else:
        result = await db.execute(
            select(Reaction).where(
                Reaction.actor_id == actor.id,
                Reaction.note_id == note.id,
            )
        )

    reaction = result.scalar_one_or_none()
    if reaction:
        await db.delete(reaction)
        note.reactions_count = max(0, note.reactions_count - 1)
        await db.commit()
        logger.info("Undo reaction from %s on %s", actor_ap_id, note_ap_id)
