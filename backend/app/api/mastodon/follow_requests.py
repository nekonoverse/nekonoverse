"""Mastodon-compatible follow requests API."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.dependencies import get_current_user, get_db
from app.models.actor import Actor
from app.models.follow import Follow
from app.models.user import User
from app.utils.media_proxy import media_proxy_url

router = APIRouter(prefix="/api/v1/follow_requests", tags=["follow_requests"])


def _account_response(actor: Actor) -> dict:
    avatar = media_proxy_url(actor.avatar_url) if actor.avatar_url else None
    header = media_proxy_url(actor.header_url) if actor.header_url else None
    return {
        "id": str(actor.id),
        "username": actor.username,
        "acct": actor.username if not actor.domain else f"{actor.username}@{actor.domain}",
        "display_name": actor.display_name or actor.username,
        "avatar": avatar or "",
        "avatar_static": avatar or "",
        "header": header or "",
        "header_static": header or "",
        "locked": actor.manually_approves_followers,
        "url": actor.ap_id or "",
        "emojis": [],
    }


@router.get("")
async def list_follow_requests(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List pending follow requests for the current user."""
    result = await db.execute(
        select(Follow)
        .options(joinedload(Follow.follower))
        .where(
            Follow.following_id == user.actor_id,
            Follow.accepted == False,  # noqa: E712
        )
        .order_by(Follow.created_at.desc())
    )
    follows = result.scalars().unique().all()
    return [_account_response(f.follower) for f in follows]


@router.post("/{account_id}/authorize")
async def authorize_follow_request(
    account_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Accept a pending follow request."""
    result = await db.execute(
        select(Follow)
        .options(joinedload(Follow.follower))
        .where(
            Follow.follower_id == account_id,
            Follow.following_id == user.actor_id,
            Follow.accepted == False,  # noqa: E712
        )
    )
    follow = result.scalars().first()
    if not follow:
        raise HTTPException(status_code=404, detail="Follow request not found")

    follow.accepted = True
    await db.flush()

    # Create "follow" notification now that the request is accepted
    from app.services.notification_service import create_notification, publish_notification

    notif = await create_notification(db, "follow", user.actor_id, account_id)
    if notif:
        await db.flush()
        await publish_notification(notif)

    # Send Accept activity to remote follower
    follower = follow.follower
    if follower and not follower.is_local and follower.inbox_url:
        from app.activitypub.renderer import render_accept_activity, render_follow_activity
        from app.services.delivery_service import enqueue_delivery

        follow_activity = render_follow_activity(
            follow.ap_id or f"{follower.ap_id}#follows/{user.actor_id}",
            follower.ap_id,
            user.actor.ap_id,
        )
        accept_id = f"{user.actor.ap_id}#accepts/follows/{follower.id}"
        accept = render_accept_activity(accept_id, user.actor.ap_id, follow_activity)
        await enqueue_delivery(db, user.actor_id, follower.inbox_url, accept)

    await db.commit()
    return {"id": str(account_id), "following": False, "followed_by": True}


@router.post("/{account_id}/reject")
async def reject_follow_request(
    account_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reject a pending follow request."""
    result = await db.execute(
        select(Follow)
        .options(joinedload(Follow.follower))
        .where(
            Follow.follower_id == account_id,
            Follow.following_id == user.actor_id,
            Follow.accepted == False,  # noqa: E712
        )
    )
    follow = result.scalars().first()
    if not follow:
        raise HTTPException(status_code=404, detail="Follow request not found")

    follower = follow.follower
    await db.delete(follow)
    await db.flush()

    # Send Reject activity to remote follower
    if follower and not follower.is_local and follower.inbox_url:
        from app.activitypub.renderer import render_follow_activity, render_reject_activity
        from app.services.delivery_service import enqueue_delivery

        follow_activity = render_follow_activity(
            follow.ap_id or f"{follower.ap_id}#follows/{user.actor_id}",
            follower.ap_id,
            user.actor.ap_id,
        )
        reject_id = f"{user.actor.ap_id}#rejects/follows/{follower.id}"
        reject = render_reject_activity(reject_id, user.actor.ap_id, follow_activity)
        await enqueue_delivery(db, user.actor_id, follower.inbox_url, reject)

    await db.commit()
    return {"id": str(account_id), "following": False, "followed_by": False}
