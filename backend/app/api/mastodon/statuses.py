import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_current_user, get_db, get_optional_user
from app.models.note import Note
from app.models.user import User
from app.schemas.note import NoteActorResponse, NoteCreateRequest, NoteMediaAttachment, NoteResponse, PollResponse, PollOptionResponse, ReactionSummary
from app.services.actor_service import actor_uri
from app.services.note_service import check_note_visible, create_note, get_note_by_id, get_reaction_summary

router = APIRouter(prefix="/api/v1/statuses", tags=["statuses"])


def _attachment_to_media(att) -> NoteMediaAttachment:
    """Convert a NoteAttachment to NoteMediaAttachment for API response."""
    if att.drive_file:
        from app.services.drive_service import file_to_url
        url = file_to_url(att.drive_file)
        mime = att.drive_file.mime_type or ""
        meta = None
        if att.drive_file.width and att.drive_file.height:
            meta = {"original": {"width": att.drive_file.width, "height": att.drive_file.height}}
        return NoteMediaAttachment(
            id=str(att.id),
            type="image" if mime.startswith("image/") else "unknown",
            url=url,
            preview_url=url,
            description=att.drive_file.description,
            blurhash=att.drive_file.blurhash,
            meta=meta,
        )
    # Remote attachment
    mime = att.remote_mime_type or ""
    meta = None
    if att.remote_width and att.remote_height:
        meta = {"original": {"width": att.remote_width, "height": att.remote_height}}
    return NoteMediaAttachment(
        id=str(att.id),
        type="image" if mime.startswith("image/") else "unknown",
        url=att.remote_url or "",
        preview_url=att.remote_url or "",
        description=att.remote_description,
        blurhash=att.remote_blurhash,
        meta=meta,
    )


def note_to_response(note, reactions: list[dict] | None = None, reblog_note=None) -> NoteResponse:
    actor = note.actor
    reblog = None
    if reblog_note:
        reblog = note_to_response(reblog_note)

    # Build media attachments
    media_attachments = []
    for att in (note.attachments or []):
        if att.drive_file or att.remote_url:
            media_attachments.append(_attachment_to_media(att))

    # Build quote
    quote = None
    if hasattr(note, 'quoted_note') and note.quoted_note:
        quote = note_to_response(note.quoted_note)

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
        media_attachments=media_attachments,
        quote=quote,
    )


@router.post("", response_model=NoteResponse, status_code=201)
async def create_status(
    body: NoteCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    poll_options = None
    poll_expires_in = None
    poll_multiple = False
    if body.poll:
        poll_options = body.poll.options
        poll_expires_in = body.poll.expires_in
        poll_multiple = body.poll.multiple

    note = await create_note(
        db=db,
        user=user,
        content=body.content,
        visibility=body.visibility,
        sensitive=body.sensitive,
        spoiler_text=body.spoiler_text,
        in_reply_to_id=body.in_reply_to_id,
        media_ids=body.media_ids or None,
        quote_id=body.quote_id,
        poll_options=poll_options,
        poll_expires_in=poll_expires_in,
        poll_multiple=poll_multiple,
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
    if not await check_note_visible(db, note, actor_id):
        raise HTTPException(status_code=404, detail="Note not found")

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

    # Notify note author
    if note.actor.is_local:
        from app.services.notification_service import create_notification
        await create_notification(
            db, "reaction", note.actor_id, user.actor_id, note.id,
            reaction_emoji=emoji,
        )
        await db.commit()

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


@router.get("/{note_id}/reacted_by")
async def reacted_by(
    note_id: uuid.UUID,
    emoji: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    from app.models.actor import Actor
    from app.models.reaction import Reaction

    note = await get_note_by_id(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    query = (
        select(Reaction)
        .options(selectinload(Reaction.actor))
        .where(Reaction.note_id == note.id)
        .order_by(Reaction.created_at.desc())
    )
    if emoji:
        query = query.where(Reaction.emoji == emoji)

    result = await db.execute(query)
    reactions = result.scalars().all()

    return [
        {
            "actor": NoteActorResponse(
                id=r.actor.id,
                username=r.actor.username,
                display_name=r.actor.display_name,
                avatar_url=r.actor.avatar_url or "/default-avatar.svg",
                ap_id=r.actor.ap_id,
                domain=r.actor.domain,
            ),
            "emoji": r.emoji,
        }
        for r in reactions
    ]


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

    # Notify original note author
    if original.actor.is_local:
        from app.services.notification_service import create_notification
        await create_notification(
            db, "renote", original.actor_id, actor.id, original.id,
        )
        await db.commit()

    await db.refresh(reblog_note, ["actor", "attachments"])

    # Deliver Announce to followers
    from app.activitypub.renderer import render_announce_activity
    from app.services.delivery_service import enqueue_delivery
    from app.services.follow_service import get_follower_inboxes

    activity = render_announce_activity(
        activity_id=ap_id,
        actor_ap_id=actor_uri(actor),
        note_ap_id=original.ap_id,
        to=to_list,
        cc=cc_list,
        published=reblog_note.published.isoformat() + "Z",
    )
    inboxes = await get_follower_inboxes(db, actor.id)
    for inbox_url in inboxes:
        await enqueue_delivery(db, actor.id, inbox_url, activity)

    # Re-refresh after delivery commits expired the session
    await db.refresh(reblog_note, ["actor", "attachments"])
    await db.refresh(original, ["actor", "attachments"])
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
        actor_ap_id=actor_uri(actor),
        note_ap_id=original.ap_id,
        to=reblog_note.to,
        cc=reblog_note.cc,
        published=reblog_note.published.isoformat() + "Z",
    )
    undo_id = f"{reblog_note.ap_id}/undo"
    undo_activity = render_undo_activity(undo_id, actor_uri(actor), announce_activity)
    inboxes = await get_follower_inboxes(db, actor.id)
    for inbox_url in inboxes:
        await enqueue_delivery(db, actor.id, inbox_url, undo_activity)

    return {"ok": True}


@router.post("/{note_id}/bookmark")
async def bookmark_status(
    note_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.bookmark_service import create_bookmark

    note = await get_note_by_id(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    try:
        await create_bookmark(db, user.actor_id, note_id)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"ok": True}


@router.post("/{note_id}/unbookmark")
async def unbookmark_status(
    note_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.bookmark_service import remove_bookmark

    note = await get_note_by_id(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    try:
        await remove_bookmark(db, user.actor_id, note_id)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"ok": True}


@router.post("/{note_id}/pin")
async def pin_status(
    note_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.pinned_note_service import pin_note

    try:
        await pin_note(db, user, note_id)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Deliver Add activity to followers
    from app.activitypub.renderer import render_add_activity
    from app.config import settings
    from app.services.delivery_service import enqueue_delivery
    from app.services.follow_service import get_follower_inboxes

    actor = user.actor
    note = await get_note_by_id(db, note_id)
    activity = render_add_activity(
        activity_id=f"{actor_uri(actor)}/add/{note_id}",
        actor_ap_id=actor_uri(actor),
        object_id=note.ap_id,
        target=f"{settings.server_url}/users/{actor.username}/featured",
    )
    inboxes = await get_follower_inboxes(db, actor.id)
    for inbox_url in inboxes:
        await enqueue_delivery(db, actor.id, inbox_url, activity)

    return {"ok": True}


@router.post("/{note_id}/unpin")
async def unpin_status(
    note_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.pinned_note_service import unpin_note

    note = await get_note_by_id(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    try:
        await unpin_note(db, user, note_id)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Deliver Remove activity to followers
    from app.activitypub.renderer import render_remove_activity
    from app.config import settings
    from app.services.delivery_service import enqueue_delivery
    from app.services.follow_service import get_follower_inboxes

    actor = user.actor
    activity = render_remove_activity(
        activity_id=f"{actor_uri(actor)}/remove/{note_id}",
        actor_ap_id=actor_uri(actor),
        object_id=note.ap_id,
        target=f"{settings.server_url}/users/{actor.username}/featured",
    )
    inboxes = await get_follower_inboxes(db, actor.id)
    for inbox_url in inboxes:
        await enqueue_delivery(db, actor.id, inbox_url, activity)

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
        actor_ap_id=actor_uri(actor),
        object_id=note.ap_id,
    )
    inboxes = await get_follower_inboxes(db, actor.id)
    for inbox_url in inboxes:
        await enqueue_delivery(db, actor.id, inbox_url, delete_activity)

    return Response(status_code=204)
