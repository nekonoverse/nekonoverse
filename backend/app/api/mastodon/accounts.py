import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.actor import Actor
from app.models.follow import Follow
from app.models.user import User
from app.services.actor_service import fetch_remote_actor, get_actor_by_ap_id
from app.services.follow_service import follow_actor, unfollow_actor

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])


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
    """Lookup an account by acct URI (user@domain)."""
    if "@" in acct:
        username, domain = acct.split("@", 1)
    else:
        username = acct
        domain = None

    from app.services.actor_service import get_actor_by_username

    actor = await get_actor_by_username(db, username, domain)
    if not actor:
        raise HTTPException(status_code=404, detail="Account not found")

    return {
        "id": str(actor.id),
        "username": actor.username,
        "acct": f"{actor.username}@{actor.domain}" if actor.domain else actor.username,
        "display_name": actor.display_name,
        "note": actor.summary or "",
        "url": actor.ap_id,
    }


@router.get("/{actor_id}")
async def get_account(actor_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Actor).where(Actor.id == actor_id))
    actor = result.scalar_one_or_none()
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    return {
        "id": str(actor.id),
        "username": actor.username,
        "acct": f"{actor.username}@{actor.domain}" if actor.domain else actor.username,
        "display_name": actor.display_name,
        "note": actor.summary or "",
        "avatar": actor.avatar_url or "",
        "header": actor.header_url or "",
        "url": actor.ap_id,
        "created_at": actor.created_at.isoformat(),
    }
