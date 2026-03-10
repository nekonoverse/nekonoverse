"""Pinned note service: pin, unpin, list pinned notes."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.note import Note
from app.models.pinned_note import PinnedNote
from app.models.user import User

MAX_PINS = 5


async def pin_note(db: AsyncSession, user: User, note_id: uuid.UUID) -> PinnedNote:
    """Pin a note. Raises ValueError if limit exceeded or already pinned."""
    actor = user.actor

    # Verify the note exists and belongs to the user
    result = await db.execute(select(Note).where(Note.id == note_id, Note.deleted_at.is_(None)))
    note = result.scalar_one_or_none()
    if not note:
        raise ValueError("Note not found")
    if note.actor_id != actor.id:
        raise ValueError("Can only pin your own notes")

    # Check if already pinned
    existing = await db.execute(
        select(PinnedNote).where(PinnedNote.actor_id == actor.id, PinnedNote.note_id == note_id)
    )
    if existing.scalar_one_or_none():
        raise ValueError("Already pinned")

    # Check pin count
    count_result = await db.execute(
        select(func.count()).select_from(PinnedNote).where(PinnedNote.actor_id == actor.id)
    )
    count = count_result.scalar() or 0
    if count >= MAX_PINS:
        raise ValueError(f"Maximum {MAX_PINS} pinned notes allowed")

    pin = PinnedNote(
        actor_id=actor.id,
        note_id=note_id,
        position=count,
    )
    db.add(pin)
    await db.flush()
    return pin


async def unpin_note(db: AsyncSession, user: User, note_id: uuid.UUID) -> None:
    """Unpin a note. Raises ValueError if not pinned."""
    actor = user.actor

    result = await db.execute(
        select(PinnedNote).where(PinnedNote.actor_id == actor.id, PinnedNote.note_id == note_id)
    )
    pin = result.scalar_one_or_none()
    if not pin:
        raise ValueError("Not pinned")

    await db.delete(pin)
    await db.flush()


async def get_pinned_notes(db: AsyncSession, actor_id: uuid.UUID) -> list[PinnedNote]:
    """Get pinned notes for an actor, ordered by position."""
    result = await db.execute(
        select(PinnedNote)
        .options(
            selectinload(PinnedNote.note).selectinload(Note.actor),
            selectinload(PinnedNote.note).selectinload(Note.attachments),
            selectinload(PinnedNote.note).selectinload(Note.quoted_note).selectinload(Note.actor),
            selectinload(PinnedNote.note)
            .selectinload(Note.quoted_note)
            .selectinload(Note.attachments),
            selectinload(PinnedNote.note).selectinload(Note.renote_of).selectinload(Note.actor),
            selectinload(PinnedNote.note)
            .selectinload(Note.renote_of)
            .selectinload(Note.attachments),
        )
        .where(PinnedNote.actor_id == actor_id)
        .order_by(PinnedNote.position)
    )
    return list(result.scalars().all())
