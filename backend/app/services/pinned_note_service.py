"""ピン留めノートサービス: ピン留め、ピン解除、ピン留めノート一覧。"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.note import Note
from app.models.pinned_note import PinnedNote
from app.models.user import User

MAX_PINS = 5


async def pin_note(db: AsyncSession, user: User, note_id: uuid.UUID) -> PinnedNote:
    """ノートをピン留めする。上限超過または既にピン留め済みの場合はValueErrorを送出。"""
    actor = user.actor

    # ノートの存在と所有者の確認
    result = await db.execute(select(Note).where(Note.id == note_id, Note.deleted_at.is_(None)))
    note = result.scalar_one_or_none()
    if not note:
        raise ValueError("Note not found")
    if note.actor_id != actor.id:
        raise ValueError("Can only pin your own notes")

    # 既にピン留め済みか確認
    existing = await db.execute(
        select(PinnedNote).where(PinnedNote.actor_id == actor.id, PinnedNote.note_id == note_id)
    )
    if existing.scalar_one_or_none():
        raise ValueError("Already pinned")

    # ピン留め数の確認
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
    """ノートのピン留めを解除する。ピン留めされていない場合はValueErrorを送出。"""
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
    """アクターのピン留めノートを position 順で取得する。"""
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
