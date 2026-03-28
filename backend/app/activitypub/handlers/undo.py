"""Undo activity を処理する (Undo Follow, Undo Like, Undo Announce 等)。"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.follow import Follow
from app.models.note import Note
from app.models.reaction import Reaction
from app.models.user_block import UserBlock
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
    elif inner_type == "Announce":
        await _undo_announce(db, activity, inner)
    elif inner_type == "Block":
        await _undo_block(db, activity, inner)
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

    # ap_id または actor+note でリアクションを検索
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

        from app.services.reaction_service import _publish_reaction_event

        await _publish_reaction_event(db, note)

        logger.info("Undo reaction from %s on %s", actor_ap_id, note_ap_id)


async def _undo_announce(db: AsyncSession, activity: dict, inner: dict):
    actor_ap_id = inner.get("actor") or activity.get("actor")
    if not actor_ap_id:
        return

    actor = await get_actor_by_ap_id(db, actor_ap_id)
    if not actor:
        return

    # Announce ノートを AP ID で検索
    announce_ap_id = inner.get("id")
    if not announce_ap_id:
        return

    announce_note = await get_note_by_ap_id(db, announce_ap_id)
    if not announce_note or announce_note.actor_id != actor.id:
        return

    # Announce を論理削除
    announce_note.deleted_at = datetime.now(timezone.utc)

    # 元ノートの renotes_count をデクリメント
    if announce_note.renote_of_id:
        result = await db.execute(select(Note).where(Note.id == announce_note.renote_of_id))
        original = result.scalar_one_or_none()
        if original:
            original.renotes_count = max(0, original.renotes_count - 1)

    await db.commit()
    logger.info("Undo Announce %s from %s", announce_ap_id, actor_ap_id)


async def _undo_block(db: AsyncSession, activity: dict, inner: dict):
    actor_ap_id = inner.get("actor") or activity.get("actor")
    target_ap_id = inner.get("object")

    if not actor_ap_id or not target_ap_id:
        return

    blocker = await get_actor_by_ap_id(db, actor_ap_id)
    target = await get_actor_by_ap_id(db, target_ap_id)

    if not blocker or not target:
        return

    result = await db.execute(
        select(UserBlock).where(
            UserBlock.actor_id == blocker.id,
            UserBlock.target_id == target.id,
        )
    )
    block = result.scalar_one_or_none()
    if block:
        await db.delete(block)
        await db.commit()
        logger.info("Undo block: %s -> %s", actor_ap_id, target_ap_id)
