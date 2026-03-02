"""Handle Like and EmojiReact activities (Misskey/Pleroma compatible)."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reaction import Reaction
from app.services.actor_service import fetch_remote_actor, get_actor_by_ap_id
from app.services.note_service import get_note_by_ap_id
from app.utils.emoji import is_single_emoji

logger = logging.getLogger(__name__)


async def handle_like(db: AsyncSession, activity: dict):
    """Handle Like activity -- may contain Misskey-style _misskey_reaction."""
    actor_ap_id = activity.get("actor")
    note_ap_id = activity.get("object")

    if not actor_ap_id or not note_ap_id:
        return

    # Determine emoji
    misskey_reaction = activity.get("_misskey_reaction")
    content = activity.get("content")

    if misskey_reaction:
        emoji = misskey_reaction
    elif content and is_single_emoji(content):
        emoji = content
    else:
        emoji = "\u2764"  # ❤

    await _save_reaction(db, activity, actor_ap_id, note_ap_id, emoji)


async def handle_emoji_react(db: AsyncSession, activity: dict):
    """Handle EmojiReact activity (Pleroma/Akkoma style)."""
    actor_ap_id = activity.get("actor")
    note_ap_id = activity.get("object")
    content = activity.get("content")

    if not actor_ap_id or not note_ap_id:
        return

    emoji = content if content and is_single_emoji(content) else "\u2764"
    await _save_reaction(db, activity, actor_ap_id, note_ap_id, emoji)


async def _save_reaction(
    db: AsyncSession,
    activity: dict,
    actor_ap_id: str,
    note_ap_id: str,
    emoji: str,
):
    # Resolve actor
    actor = await get_actor_by_ap_id(db, actor_ap_id)
    if not actor:
        actor = await fetch_remote_actor(db, actor_ap_id)
    if not actor:
        logger.warning("Could not resolve actor %s for reaction", actor_ap_id)
        return

    # Resolve note
    note = await get_note_by_ap_id(db, note_ap_id)
    if not note:
        logger.info("Note not found for reaction: %s", note_ap_id)
        return

    # Check for duplicate
    existing = await db.execute(
        select(Reaction).where(
            Reaction.actor_id == actor.id,
            Reaction.note_id == note.id,
            Reaction.emoji == emoji,
        )
    )
    if existing.scalar_one_or_none():
        return

    reaction = Reaction(
        ap_id=activity.get("id"),
        actor_id=actor.id,
        note_id=note.id,
        emoji=emoji,
    )
    db.add(reaction)

    # Update reaction count
    note.reactions_count = note.reactions_count + 1
    await db.commit()

    logger.info("Saved reaction %s from %s on %s", emoji, actor_ap_id, note_ap_id)
