import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_current_user, get_db
from app.models.actor import Actor
from app.models.follow import Follow
from app.models.note import Note
from app.models.user import User
from app.services.actor_service import fetch_remote_actor, get_actor_by_ap_id
from app.services.follow_service import follow_actor, unfollow_actor

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])
relationships_router = APIRouter(prefix="/api/v1", tags=["relationships"])


@router.post("/{actor_id}/follow")
async def follow(
    actor_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Actor).where(Actor.id == actor_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Actor not found")

    if target.id == user.actor_id:
        raise HTTPException(status_code=422, detail="Cannot follow yourself")

    try:
        await follow_actor(db, user, target)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"ok": True}


@router.post("/{actor_id}/unfollow")
async def unfollow(
    actor_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Actor).where(Actor.id == actor_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Actor not found")

    try:
        await unfollow_actor(db, user, target)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"ok": True}


@router.get("/lookup")
async def lookup_account(
    acct: str,
    db: AsyncSession = Depends(get_db),
):
    """Lookup an account by acct URI (user@domain). Resolves remote actors via WebFinger."""
    if "@" in acct:
        username, domain = acct.split("@", 1)
    else:
        username = acct
        domain = None

    from app.services.actor_service import get_actor_by_username

    actor = await get_actor_by_username(db, username, domain)

    # If not found locally and it's a remote acct, resolve via WebFinger
    if not actor and domain:
        from app.services.actor_service import resolve_webfinger

        actor = await resolve_webfinger(db, username, domain)

    if not actor:
        raise HTTPException(status_code=404, detail="Account not found")

    return _actor_to_account(actor)


@router.get("/search")
async def search_accounts(
    q: str,
    resolve: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Search for accounts. If resolve=true and q looks like user@domain, resolve via WebFinger."""
    acct = q.lstrip("@")

    if "@" in acct:
        username, domain = acct.split("@", 1)
    else:
        username = acct
        domain = None

    from app.services.actor_service import get_actor_by_username

    actor = await get_actor_by_username(db, username, domain)

    if not actor and domain and resolve:
        from app.services.actor_service import resolve_webfinger

        actor = await resolve_webfinger(db, username, domain)

    if not actor:
        return []

    return [_actor_to_account(actor)]


def _actor_to_account(actor: Actor) -> dict:
    return {
        "id": str(actor.id),
        "username": actor.username,
        "acct": f"{actor.username}@{actor.domain}" if actor.domain else actor.username,
        "display_name": actor.display_name,
        "note": actor.summary or "",
        "avatar": actor.avatar_url or "/default-avatar.svg",
        "header": actor.header_url or "",
        "url": actor.ap_id,
        "created_at": actor.created_at.isoformat() if actor.created_at else None,
    }


@router.post("/{actor_id}/block")
async def block_account(
    actor_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.block_service import block_actor

    result = await db.execute(select(Actor).where(Actor.id == actor_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Actor not found")
    if target.id == user.actor_id:
        raise HTTPException(status_code=422, detail="Cannot block yourself")

    try:
        await block_actor(db, user, target)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"ok": True}


@router.post("/{actor_id}/unblock")
async def unblock_account(
    actor_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.block_service import unblock_actor

    result = await db.execute(select(Actor).where(Actor.id == actor_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Actor not found")

    try:
        await unblock_actor(db, user, target)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"ok": True}


@router.post("/{actor_id}/mute")
async def mute_account(
    actor_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.mute_service import mute_actor

    result = await db.execute(select(Actor).where(Actor.id == actor_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Actor not found")
    if target.id == user.actor_id:
        raise HTTPException(status_code=422, detail="Cannot mute yourself")

    try:
        await mute_actor(db, user, target)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"ok": True}


@router.post("/{actor_id}/unmute")
async def unmute_account(
    actor_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.mute_service import unmute_actor

    result = await db.execute(select(Actor).where(Actor.id == actor_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Actor not found")

    try:
        await unmute_actor(db, user, target)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"ok": True}


@router.get("/{actor_id}/statuses")
async def get_account_statuses(
    actor_id: uuid.UUID,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Actor).where(Actor.id == actor_id))
    actor = result.scalar_one_or_none()
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    from app.schemas.note import NoteActorResponse, NoteResponse, ReactionSummary
    from app.services.note_service import get_reaction_summary

    notes_result = await db.execute(
        select(Note)
        .options(selectinload(Note.actor))
        .where(
            Note.actor_id == actor_id,
            Note.visibility.in_(["public", "unlisted"]),
            Note.deleted_at.is_(None),
        )
        .order_by(Note.published.desc())
        .limit(min(limit, 40))
    )
    notes = notes_result.scalars().all()

    response = []
    for note in notes:
        reactions = await get_reaction_summary(db, note.id, None)
        a = note.actor
        response.append(NoteResponse(
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
                id=a.id,
                username=a.username,
                display_name=a.display_name,
                avatar_url=a.avatar_url or "/default-avatar.svg",
                ap_id=a.ap_id,
                domain=a.domain,
            ),
            reactions=[ReactionSummary(**r) for r in (reactions or [])],
        ))
    return response


@router.get("/{actor_id}")
async def get_account(actor_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Actor).where(Actor.id == actor_id))
    actor = result.scalar_one_or_none()
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    return _actor_to_account(actor)


# --- Block/Mute lists (different prefix) ---


@relationships_router.get("/blocks")
async def list_blocks(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.block_service import get_blocked_ids

    blocked_ids = await get_blocked_ids(db, user.actor_id)
    if not blocked_ids:
        return []

    result = await db.execute(select(Actor).where(Actor.id.in_(blocked_ids)))
    actors = result.scalars().all()
    return [_actor_to_account(a) for a in actors]


@relationships_router.get("/mutes")
async def list_mutes(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.mute_service import get_muted_ids

    muted_ids = await get_muted_ids(db, user.actor_id)
    if not muted_ids:
        return []

    result = await db.execute(select(Actor).where(Actor.id.in_(muted_ids)))
    actors = result.scalars().all()
    return [_actor_to_account(a) for a in actors]
