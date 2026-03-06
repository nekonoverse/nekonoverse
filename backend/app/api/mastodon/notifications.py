"""Notification API endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.note import NoteActorResponse
from app.schemas.notification import NotificationResponse

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


def _notification_to_response(notif) -> NotificationResponse:
    account = None
    if notif.sender:
        account = NoteActorResponse(
            id=notif.sender.id,
            username=notif.sender.username,
            display_name=notif.sender.display_name,
            avatar_url=notif.sender.avatar_url or "/default-avatar.svg",
            ap_id=notif.sender.ap_id,
            domain=notif.sender.domain,
        )

    status = None
    if notif.note:
        from app.api.mastodon.statuses import note_to_response
        status = note_to_response(notif.note)

    return NotificationResponse(
        id=notif.id,
        type=notif.type,
        created_at=notif.created_at,
        read=notif.read,
        account=account,
        status=status,
        emoji=notif.reaction_emoji,
    )


@router.get("", response_model=list[NotificationResponse])
async def get_notifications(
    max_id: uuid.UUID | None = Query(None),
    limit: int = Query(20, ge=1, le=40),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.notification_service import get_notifications as _get

    notifications = await _get(db, user.actor_id, limit=limit, max_id=max_id)
    return [_notification_to_response(n) for n in notifications]


@router.post("/{notification_id}/dismiss")
async def dismiss_notification(
    notification_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.notification_service import mark_as_read

    success = await mark_as_read(db, notification_id, user.actor_id)
    if not success:
        raise HTTPException(status_code=404, detail="Notification not found")
    await db.commit()
    return {"ok": True}


@router.post("/clear")
async def clear_all_notifications(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.notification_service import clear_notifications

    await clear_notifications(db, user.actor_id)
    await db.commit()
    return {"ok": True}
