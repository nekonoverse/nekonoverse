import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, get_optional_user
from app.models.user import User
from app.schemas.note import NoteActorResponse, NoteCreateRequest, NoteResponse, ReactionSummary
from app.services.note_service import create_note, get_note_by_id, get_reaction_summary

router = APIRouter(prefix="/api/v1/statuses", tags=["statuses"])


def note_to_response(note, reactions: list[dict] | None = None) -> NoteResponse:
    actor = note.actor
    return NoteResponse(
        id=note.id,
        ap_id=note.ap_id,
        content=note.content,
        source=note.source,
        visibility=note.visibility,
        sensitive=note.sensitive,
        spoiler_text=note.spoiler_text,
        published=note.published,
        replies_count=note.replies_count,
        reactions_count=note.reactions_count,
        renotes_count=note.renotes_count,
        actor=NoteActorResponse(
            id=actor.id,
            username=actor.username,
            display_name=actor.display_name,
            avatar_url=actor.avatar_url or "/default-avatar.svg",
            ap_id=actor.ap_id,
            domain=actor.domain,
        ),
        reactions=[ReactionSummary(**r) for r in (reactions or [])],
    )


@router.post("", response_model=NoteResponse, status_code=201)
async def create_status(
    body: NoteCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    note = await create_note(
        db=db,
        user=user,
        content=body.content,
        visibility=body.visibility,
        sensitive=body.sensitive,
        spoiler_text=body.spoiler_text,
        in_reply_to_id=body.in_reply_to_id,
    )
    return note_to_response(note)


@router.get("/{note_id}", response_model=NoteResponse)
async def get_status(
    note_id: uuid.UUID,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    note = await get_note_by_id(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    actor_id = user.actor_id if user else None
    reactions = await get_reaction_summary(db, note.id, actor_id)
    return note_to_response(note, reactions)


@router.post("/{note_id}/react/{emoji}")
async def react_to_note(
    note_id: uuid.UUID,
    emoji: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.reaction_service import add_reaction

    note = await get_note_by_id(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    try:
        await add_reaction(db, user, note, emoji)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"ok": True}


@router.post("/{note_id}/unreact/{emoji}")
async def unreact_to_note(
    note_id: uuid.UUID,
    emoji: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.reaction_service import remove_reaction

    note = await get_note_by_id(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    try:
        await remove_reaction(db, user, note, emoji)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
