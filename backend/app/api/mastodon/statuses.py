import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_current_user, get_db, get_optional_user
from app.models.note import Note
from app.models.user import User
from app.schemas.note import NoteActorResponse, NoteCreateRequest, NoteResponse, ReactionSummary
from app.services.note_service import create_note, get_note_by_id, get_reaction_summary

router = APIRouter(prefix="/api/v1/statuses", tags=["statuses"])


def note_to_response(note, reactions: list[dict] | None = None, reblog_note=None) -> NoteResponse:
    actor = note.actor
    reblog = None
    if reblog_note:
        reblog = note_to_response(reblog_note)
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
        reblog=reblog,
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

    return {"ok": True}


@router.post("/{note_id}/reblog", response_model=NoteResponse, status_code=200)
async def reblog_status(
    note_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    original = await get_note_by_id(db, note_id)
    if not original:
        raise HTTPException(status_code=404, detail="Note not found")

    actor = user.actor

    # Check for existing reblog
    existing = await db.execute(
        select(Note).where(
            Note.actor_id == actor.id,
            Note.renote_of_id == original.id,
            Note.deleted_at.is_(None),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=422, detail="Already reblogged")

    from app.config import settings

    reblog_id = uuid.uuid4()
    ap_id = f"{settings.server_url}/notes/{reblog_id}"

    public = "https://www.w3.org/ns/activitystreams#Public"
    to_list = [public]
    cc_list = [actor.followers_url or ""]

    reblog_note = Note(
        id=reblog_id,
        ap_id=ap_id,
        actor_id=actor.id,
        content="",
        visibility="public",
        renote_of_id=original.id,
        renote_of_ap_id=original.ap_id,
        to=to_list,
        cc=cc_list,
        local=True,
    )
    db.add(reblog_note)
    original.renotes_count = original.renotes_count + 1
    await db.commit()
    await db.refresh(reblog_note, ["actor"])

    # Deliver Announce to followers
    from app.activitypub.renderer import render_announce_activity
    from app.services.delivery_service import enqueue_delivery
    from app.services.follow_service import get_follower_inboxes

    activity = render_announce_activity(
        activity_id=ap_id,
        actor_ap_id=actor.ap_id,
        note_ap_id=original.ap_id,
        to=to_list,
        cc=cc_list,
        published=reblog_note.published.isoformat() + "Z",
    )
    inboxes = await get_follower_inboxes(db, actor.id)
    for inbox_url in inboxes:
        await enqueue_delivery(db, actor.id, inbox_url, activity)

    return note_to_response(reblog_note, reblog_note=original)


@router.post("/{note_id}/unreblog", status_code=200)
async def unreblog_status(
    note_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    original = await get_note_by_id(db, note_id)
    if not original:
        raise HTTPException(status_code=404, detail="Note not found")

    actor = user.actor

    result = await db.execute(
        select(Note)
        .options(selectinload(Note.actor))
        .where(
            Note.actor_id == actor.id,
            Note.renote_of_id == original.id,
            Note.deleted_at.is_(None),
        )
    )
    reblog_note = result.scalar_one_or_none()
    if not reblog_note:
        raise HTTPException(status_code=422, detail="Not reblogged")

    reblog_note.deleted_at = datetime.now(timezone.utc)
    original.renotes_count = max(0, original.renotes_count - 1)
    await db.commit()

    # Deliver Undo(Announce) to followers
    from app.activitypub.renderer import render_announce_activity, render_undo_activity
    from app.services.delivery_service import enqueue_delivery
    from app.services.follow_service import get_follower_inboxes

    announce_activity = render_announce_activity(
        activity_id=reblog_note.ap_id,
        actor_ap_id=actor.ap_id,
        note_ap_id=original.ap_id,
        to=reblog_note.to,
        cc=reblog_note.cc,
        published=reblog_note.published.isoformat() + "Z",
    )
    undo_id = f"{reblog_note.ap_id}/undo"
    undo_activity = render_undo_activity(undo_id, actor.ap_id, announce_activity)
    inboxes = await get_follower_inboxes(db, actor.id)
    for inbox_url in inboxes:
        await enqueue_delivery(db, actor.id, inbox_url, undo_activity)

    return {"ok": True}


@router.delete("/{note_id}", status_code=204)
async def delete_status(
    note_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    note = await get_note_by_id(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    if note.actor_id != user.actor_id:
        raise HTTPException(status_code=403, detail="Not your note")

    note.deleted_at = datetime.now(timezone.utc)
    await db.commit()

    # Deliver Delete(Tombstone) to followers
    from app.activitypub.renderer import render_delete_activity
    from app.services.delivery_service import enqueue_delivery
    from app.services.follow_service import get_follower_inboxes

    actor = user.actor
    delete_activity = render_delete_activity(
        activity_id=f"{note.ap_id}/delete",
        actor_ap_id=actor.ap_id,
        object_id=note.ap_id,
    )
    inboxes = await get_follower_inboxes(db, actor.id)
    for inbox_url in inboxes:
        await enqueue_delivery(db, actor.id, inbox_url, delete_activity)

    return Response(status_code=204)
