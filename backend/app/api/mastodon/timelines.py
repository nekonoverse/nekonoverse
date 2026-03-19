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

# Absolute upper bound (prevent abuse regardless of admin config)
_HARD_MAX_LIMIT = 200


async def _resolve_limit(db: AsyncSession, requested: int | None) -> int:
    """Clamp requested limit to admin-configured bounds."""
    from app.services.server_settings_service import get_setting

    default_s = await get_setting(db, "timeline_default_limit")
    max_s = await get_setting(db, "timeline_max_limit")
    default_limit = int(default_s) if default_s else 20
    max_limit = min(int(max_s) if max_s else 40, _HARD_MAX_LIMIT)
    if requested is None:
        return default_limit
    return max(1, min(requested, max_limit))


def _deduplicate_timeline(responses: list[NoteResponse]) -> list[NoteResponse]:
    """Remove standalone notes that already appear as a reblog in the same timeline."""
    reblogged_ids: set[uuid.UUID] = set()
    for r in responses:
        if r.reblog:
            reblogged_ids.add(r.reblog.id)
    return [r for r in responses if r.reblog or r.id not in reblogged_ids]


async def _public_tl_deduped(
    db: AsyncSession,
    limit: int,
    max_id: uuid.UUID | None,
    local: bool,
    actor_id: uuid.UUID | None,
) -> list[NoteResponse]:
    """Fetch public timeline with dedup, over-fetching to guarantee limit items."""
    # Over-fetch to compensate for items removed by dedup
    fetch_limit = limit + 10
    notes = await get_public_timeline(
        db, limit=fetch_limit, max_id=max_id, local_only=local,
        current_actor_id=actor_id,
    )
    note_ids = [n.id for n in notes]
    reactions_map = await get_reaction_summaries(db, note_ids, actor_id)
    result = await notes_to_responses(notes, reactions_map, db, actor_id=actor_id)
    deduped = _deduplicate_timeline(result)
    return deduped[:limit]


async def _home_tl_deduped(
    db: AsyncSession,
    user: User,
    limit: int,
    max_id: uuid.UUID | None,
) -> list[NoteResponse]:
    """Fetch home timeline with dedup, over-fetching to guarantee limit items."""
    fetch_limit = limit + 10
    notes = await get_home_timeline(db, user=user, limit=fetch_limit, max_id=max_id)
    note_ids = [n.id for n in notes]
    reactions_map = await get_reaction_summaries(db, note_ids, user.actor_id)
    result = await notes_to_responses(
        notes, reactions_map, db, actor_id=user.actor_id
    )
    deduped = _deduplicate_timeline(result)
    return deduped[:limit]


@router.get("/public", response_model=list[NoteResponse])
async def public_timeline(
    local: bool = Query(False),
    max_id: uuid.UUID | None = Query(None),
    limit: int | None = Query(None, ge=1),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    actual_limit = await _resolve_limit(db, limit)
    actor_id = user.actor_id if user else None
    return await _public_tl_deduped(db, actual_limit, max_id, local, actor_id)


@router.get("/home", response_model=list[NoteResponse])
async def home_timeline(
    max_id: uuid.UUID | None = Query(None),
    limit: int | None = Query(None, ge=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    actual_limit = await _resolve_limit(db, limit)
    return await _home_tl_deduped(db, user, actual_limit, max_id)


@router.get("/tag/{tag}", response_model=list[NoteResponse])
async def tag_timeline(
    tag: str,
    max_id: uuid.UUID | None = Query(None),
    limit: int | None = Query(None, ge=1),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.hashtag_service import get_notes_by_hashtag

    actual_limit = await _resolve_limit(db, limit)
    actor_id = user.actor_id if user else None
    notes = await get_notes_by_hashtag(
        db, tag_name=tag, limit=actual_limit, max_id=max_id, current_actor_id=actor_id
    )
    note_ids = [n.id for n in notes]
    reactions_map = await get_reaction_summaries(db, note_ids, actor_id)
    return await notes_to_responses(notes, reactions_map, db, actor_id=actor_id)
