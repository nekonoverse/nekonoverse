"""Bookmark service: create, remove, list, check."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bookmark import Bookmark
from app.models.note import Note
from app.services.note_service import _note_load_options


async def create_bookmark(db: AsyncSession, actor_id: uuid.UUID, note_id: uuid.UUID) -> Bookmark:
    existing = await db.execute(
        select(Bookmark).where(
            Bookmark.actor_id == actor_id,
            Bookmark.note_id == note_id,
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("Already bookmarked")

    bookmark = Bookmark(actor_id=actor_id, note_id=note_id)
    db.add(bookmark)
    await db.flush()
    return bookmark


async def remove_bookmark(db: AsyncSession, actor_id: uuid.UUID, note_id: uuid.UUID) -> None:
    result = await db.execute(
        select(Bookmark).where(
            Bookmark.actor_id == actor_id,
            Bookmark.note_id == note_id,
        )
    )
    bookmark = result.scalar_one_or_none()
    if not bookmark:
        raise ValueError("Not bookmarked")
    await db.delete(bookmark)
    await db.flush()


async def get_bookmarks(
    db: AsyncSession,
    actor_id: uuid.UUID,
    limit: int = 20,
    max_id: uuid.UUID | None = None,
) -> list[Note]:
    query = (
        select(Note)
        .join(Bookmark, Bookmark.note_id == Note.id)
        .options(*_note_load_options())
        .where(
            Bookmark.actor_id == actor_id,
            Note.deleted_at.is_(None),
        )
    )
    if max_id:
        sub = select(Bookmark.created_at).where(Bookmark.id == max_id).scalar_subquery()
        query = query.where(Bookmark.created_at < sub)
    query = query.order_by(Bookmark.created_at.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def is_bookmarked(db: AsyncSession, actor_id: uuid.UUID, note_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(Bookmark.id).where(
            Bookmark.actor_id == actor_id,
            Bookmark.note_id == note_id,
        )
    )
    return result.scalar_one_or_none() is not None
