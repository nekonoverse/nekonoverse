"""Moderation actions: suspend, silence, delete, force-sensitive."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.actor import Actor
from app.models.moderation_log import ModerationLog
from app.models.note import Note
from app.models.user import User


async def log_action(
    db: AsyncSession,
    moderator: User,
    action: str,
    target_type: str,
    target_id: str,
    reason: str | None = None,
) -> ModerationLog:
    entry = ModerationLog(
        moderator_id=moderator.id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
    )
    db.add(entry)
    await db.flush()
    return entry


async def suspend_actor(
    db: AsyncSession, actor: Actor, moderator: User, reason: str | None = None
) -> None:
    actor.suspended_at = datetime.now(timezone.utc)
    await db.flush()

    # Soft-delete all public notes from this actor
    await db.execute(
        update(Note)
        .where(Note.actor_id == actor.id, Note.deleted_at.is_(None))
        .values(deleted_at=datetime.now(timezone.utc))
    )
    await db.flush()

    await log_action(db, moderator, "suspend", "actor", str(actor.id), reason)

    # Deliver Delete(Person) to followers
    if actor.is_local:
        from app.activitypub.renderer import render_delete_activity
        from app.services.delivery_service import enqueue_delivery
        from app.services.follow_service import get_follower_inboxes

        delete_activity = render_delete_activity(
            activity_id=f"{actor.ap_id}#delete",
            actor_ap_id=actor.ap_id,
            object_id=actor.ap_id,
        )
        inboxes = await get_follower_inboxes(db, actor.id)
        for inbox_url in inboxes:
            await enqueue_delivery(db, actor.id, inbox_url, delete_activity)


async def unsuspend_actor(
    db: AsyncSession, actor: Actor, moderator: User
) -> None:
    actor.suspended_at = None
    await db.flush()
    await log_action(db, moderator, "unsuspend", "actor", str(actor.id))


async def silence_actor(
    db: AsyncSession, actor: Actor, moderator: User, reason: str | None = None
) -> None:
    actor.silenced_at = datetime.now(timezone.utc)
    await db.flush()
    await log_action(db, moderator, "silence", "actor", str(actor.id), reason)


async def unsilence_actor(
    db: AsyncSession, actor: Actor, moderator: User
) -> None:
    actor.silenced_at = None
    await db.flush()
    await log_action(db, moderator, "unsilence", "actor", str(actor.id))


async def admin_delete_note(
    db: AsyncSession, note: Note, moderator: User, reason: str | None = None
) -> None:
    note.deleted_at = datetime.now(timezone.utc)
    await db.flush()

    await log_action(db, moderator, "delete_note", "note", str(note.id), reason)

    # Deliver Delete(Tombstone) to followers
    if note.local:
        from app.activitypub.renderer import render_delete_activity
        from app.services.delivery_service import enqueue_delivery
        from app.services.follow_service import get_follower_inboxes

        delete_activity = render_delete_activity(
            activity_id=f"{note.ap_id}/delete",
            actor_ap_id=note.actor.ap_id,
            object_id=note.ap_id,
        )
        inboxes = await get_follower_inboxes(db, note.actor_id)
        for inbox_url in inboxes:
            await enqueue_delivery(db, note.actor_id, inbox_url, delete_activity)


async def force_sensitive(
    db: AsyncSession, note: Note, moderator: User
) -> None:
    note.sensitive = True
    await db.flush()
    await log_action(db, moderator, "force_sensitive", "note", str(note.id))
