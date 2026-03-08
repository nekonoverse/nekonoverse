import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, get_optional_user
from app.models.user import User
from app.schemas.note import NoteResponse
from app.services.note_service import get_home_timeline, get_public_timeline, get_reaction_summary

from .statuses import note_to_response

router = APIRouter(prefix="/api/v1/timelines", tags=["timelines"])


@router.get("/public", response_model=list[NoteResponse])
async def public_timeline(
    local: bool = Query(False),
    max_id: uuid.UUID | None = Query(None),
    limit: int = Query(20, ge=1, le=40),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    actor_id = user.actor_id if user else None
    notes = await get_public_timeline(db, limit=limit, max_id=max_id, local_only=local, current_actor_id=actor_id)
    result = []
    for n in notes:
        reactions = await get_reaction_summary(db, n.id, actor_id)
        result.append(note_to_response(n, reactions))
    return result


@router.get("/home", response_model=list[NoteResponse])
async def home_timeline(
    max_id: uuid.UUID | None = Query(None),
    limit: int = Query(20, ge=1, le=40),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    notes = await get_home_timeline(db, user=user, limit=limit, max_id=max_id)
    result = []
    for n in notes:
        reactions = await get_reaction_summary(db, n.id, user.actor_id)
        result.append(note_to_response(n, reactions))
    return result
