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
    from app.api.mastodon.statuses import note_to_response
    from app.services.bookmark_service import get_bookmarks as _get

    notes = await _get(db, user.actor_id, limit=limit, max_id=max_id)
    result = []
    for note in notes:
        result.append(await note_to_response(note, db=db))
    return result
