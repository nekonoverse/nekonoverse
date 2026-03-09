"""Notification API endpoints."""

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.note import NoteActorResponse
from app.schemas.notification import NotificationResponse
from app.utils.media_proxy import media_proxy_url

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])

_CUSTOM_EMOJI_RE = re.compile(
    r"^:([a-zA-Z0-9_]+)(?:@([a-zA-Z0-9.-]+))?:$"
)


async def _resolve_reaction_emoji_url(
    db, emoji: str | None,
) -> str | None:
    """Resolve custom emoji reaction string to its image URL."""
    if not emoji or not db:
        return None
    m = _CUSTOM_EMOJI_RE.match(emoji)
    if not m:
        return None

    from app.models.custom_emoji import CustomEmoji
    from app.services.emoji_service import get_custom_emoji

    shortcode, domain = m.group(1), m.group(2)
    # Prefer local emoji
    local = await get_custom_emoji(db, shortcode, None)
    if local:
        return media_proxy_url(local.url)
    if domain:
        remote = await get_custom_emoji(db, shortcode, domain)
        if remote:
            return media_proxy_url(remote.url)
    else:
        from sqlalchemy import select
        result = await db.execute(
            select(CustomEmoji).where(
                CustomEmoji.shortcode == shortcode,
                CustomEmoji.domain.isnot(None),
            ).limit(1)
        )
        remote = result.scalar_one_or_none()
        if remote:
            return media_proxy_url(remote.url)
    return None


async def _notification_to_response(notif, db=None) -> NotificationResponse:
    account = None
    if notif.sender:
        account = NoteActorResponse(
            id=notif.sender.id,
            username=notif.sender.username,
            display_name=notif.sender.display_name,
            avatar_url=(
                media_proxy_url(notif.sender.avatar_url)
                or "/default-avatar.svg"
            ),
            ap_id=notif.sender.ap_id,
            domain=notif.sender.domain,
        )

    status = None
    if notif.note:
        from app.api.mastodon.statuses import note_to_response
        status = await note_to_response(notif.note, db=db)

    emoji_url = await _resolve_reaction_emoji_url(
        db, notif.reaction_emoji,
    )

    return NotificationResponse(
        id=notif.id,
        type=notif.type,
        created_at=notif.created_at,
        read=notif.read,
        account=account,
        status=status,
        emoji=notif.reaction_emoji,
        emoji_url=emoji_url,
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
    result = []
    for n in notifications:
        result.append(await _notification_to_response(n, db=db))
    return result


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
