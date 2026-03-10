import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, get_optional_user
from app.models.user import User
from app.schemas.note import NoteResponse
from app.services.note_service import (
    get_home_timeline,
    get_public_timeline,
    get_reaction_summaries,
)

from .statuses import notes_to_responses

router = APIRouter(prefix="/api/v1/timelines", tags=["timelines"])


def _deduplicate_timeline(responses: list[NoteResponse]) -> list[NoteResponse]:
    """Remove standalone notes that already appear as a reblog in the same timeline."""
    reblogged_ids: set[uuid.UUID] = set()
    for r in responses:
        if r.reblog:
            reblogged_ids.add(r.reblog.id)
    return [r for r in responses if r.reblog or r.id not in reblogged_ids]


@router.get("/public", response_model=list[NoteResponse])
async def public_timeline(
    local: bool = Query(False),
    max_id: uuid.UUID | None = Query(None),
    limit: int = Query(20, ge=1, le=40),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    actor_id = user.actor_id if user else None
    notes = await get_public_timeline(
        db,
        limit=limit,
        max_id=max_id,
        local_only=local,
        current_actor_id=actor_id,
    )
    note_ids = [n.id for n in notes]
    reactions_map = await get_reaction_summaries(db, note_ids, actor_id)
    result = await notes_to_responses(notes, reactions_map, db)
    return _deduplicate_timeline(result)


@router.get("/home", response_model=list[NoteResponse])
async def home_timeline(
    max_id: uuid.UUID | None = Query(None),
    limit: int = Query(20, ge=1, le=40),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    notes = await get_home_timeline(db, user=user, limit=limit, max_id=max_id)
    note_ids = [n.id for n in notes]
    reactions_map = await get_reaction_summaries(
        db,
        note_ids,
        user.actor_id,
    )
    result = await notes_to_responses(notes, reactions_map, db)
    return _deduplicate_timeline(result)


@router.get("/tag/{tag}", response_model=list[NoteResponse])
async def tag_timeline(
    tag: str,
    max_id: uuid.UUID | None = Query(None),
    limit: int = Query(20, ge=1, le=40),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.hashtag_service import get_notes_by_hashtag

    actor_id = user.actor_id if user else None
    notes = await get_notes_by_hashtag(
        db, tag_name=tag, limit=limit, max_id=max_id, current_actor_id=actor_id
    )
    note_ids = [n.id for n in notes]
    reactions_map = await get_reaction_summaries(db, note_ids, actor_id)
    return await notes_to_responses(notes, reactions_map, db)
