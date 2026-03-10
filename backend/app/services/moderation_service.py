"""Moderation actions: suspend, silence, delete, force-sensitive."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import update
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


async def invalidate_user_sessions(user_id: uuid.UUID) -> int:
    """Delete all Valkey sessions belonging to a specific user.

    Scans all ``session:*`` keys and removes those whose value matches
    *user_id*.  Returns the number of sessions deleted.
    """
    from app.valkey_client import valkey

    user_id_str = str(user_id)
    deleted = 0
    cursor = 0
    while True:
        cursor, keys = await valkey.scan(cursor, match="session:*", count=100)
        if keys:
            for key in keys:
                val = await valkey.get(key)
                if val == user_id_str:
                    await valkey.delete(key)
                    deleted += 1
        if cursor == 0:
            break
    return deleted


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

    # Invalidate all active sessions for the suspended user
    if actor.is_local and actor.local_user:
        await invalidate_user_sessions(actor.local_user.id)

    # Deliver Delete(Person) to followers
    if actor.is_local:
        from app.activitypub.renderer import render_delete_activity
        from app.services.actor_service import actor_uri
        from app.services.delivery_service import enqueue_delivery
        from app.services.follow_service import get_follower_inboxes

        actor_url = actor_uri(actor)
        delete_activity = render_delete_activity(
            activity_id=f"{actor_url}#delete",
            actor_ap_id=actor_url,
            object_id=actor_url,
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
        from app.services.actor_service import actor_uri
        from app.services.delivery_service import enqueue_delivery
        from app.services.follow_service import get_follower_inboxes

        delete_activity = render_delete_activity(
            activity_id=f"{note.ap_id}/delete",
            actor_ap_id=actor_uri(note.actor),
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
