"""Bookmark API endpoints."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.note import NoteResponse

router = APIRouter(prefix="/api/v1/bookmarks", tags=["bookmarks"])


@router.get("", response_model=list[NoteResponse])
async def get_bookmarks(
    max_id: uuid.UUID | None = Query(None),
    limit: int = Query(20, ge=1, le=40),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.api.mastodon.statuses import notes_to_responses
    from app.services.bookmark_service import get_bookmarks as _get
    from app.services.note_service import get_reaction_summaries

    notes = await _get(db, user.actor_id, limit=limit, max_id=max_id)
    note_ids = [n.id for n in notes]
    reactions_map = await get_reaction_summaries(
        db, note_ids, user.actor_id,
    )
    return await notes_to_responses(notes, reactions_map, db)
