"""Notification API endpoints."""

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.custom_emoji import CustomEmoji
from app.models.user import User
from app.schemas.note import CustomEmojiInfo, NoteActorResponse
from app.schemas.notification import NotificationResponse
from app.utils.media_proxy import media_proxy_url

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])

_CUSTOM_EMOJI_RE = re.compile(r"^:([a-zA-Z0-9_]+)(?:@([a-zA-Z0-9.-]+))?:$")
_SHORTCODE_RE = re.compile(r":([a-zA-Z0-9_]+):")


async def _resolve_actor_emojis(
    db,
    display_name: str | None,
    domain: str | None,
) -> list[CustomEmojiInfo]:
    """Resolve custom emojis in an actor's display_name."""
    if not display_name or not db:
        return []
    shortcodes = set(_SHORTCODE_RE.findall(display_name))
    if not shortcodes:
        return []

    from app.services.emoji_service import get_emojis_by_shortcodes

    emoji_list = await get_emojis_by_shortcodes(db, shortcodes, domain)
    if domain is not None:
        found = {e.shortcode for e in emoji_list}
        missing = shortcodes - found
        if missing:
            local_emojis = await get_emojis_by_shortcodes(db, missing, None)
            emoji_list.extend(local_emojis)

    result: list[CustomEmojiInfo] = []
    for emoji in emoji_list:
        url = media_proxy_url(emoji.url)
        static = media_proxy_url(emoji.static_url) if emoji.static_url else url
        result.append(CustomEmojiInfo(shortcode=emoji.shortcode, url=url, static_url=static))
    return result


async def _batch_resolve_emoji_urls(
    db,
    emoji_strings: list[str | None],
) -> dict[str, str | None]:
    """Batch-resolve custom emoji reaction strings to image URLs."""
    # カスタム絵文字のshortcodeを収集
    parsed: dict[str, tuple[str, str | None]] = {}
    for emoji in emoji_strings:
        if not emoji:
            continue
        m = _CUSTOM_EMOJI_RE.match(emoji)
        if m:
            parsed[emoji] = (m.group(1), m.group(2))

    if not parsed:
        return {}

    all_shortcodes = {sc for sc, _ in parsed.values()}

    # ローカル絵文字を一括取得
    local_result = await db.execute(
        select(CustomEmoji).where(
            CustomEmoji.shortcode.in_(all_shortcodes),
            CustomEmoji.domain.is_(None),
        )
    )
    local_map = {e.shortcode: e.url for e in local_result.scalars().all()}

    # ローカルにないshortcodeのリモート絵文字を一括取得
    missing = all_shortcodes - set(local_map.keys())
    remote_map: dict[str, str] = {}
    if missing:
        remote_result = await db.execute(
            select(CustomEmoji).where(
                CustomEmoji.shortcode.in_(missing),
                CustomEmoji.domain.isnot(None),
            )
        )
        for e in remote_result.scalars().all():
            if e.shortcode not in remote_map:
                remote_map[e.shortcode] = e.url

    # 結果マップを構築
    url_map: dict[str, str | None] = {}
    for emoji_str, (shortcode, _domain) in parsed.items():
        url = local_map.get(shortcode) or remote_map.get(shortcode)
        url_map[emoji_str] = media_proxy_url(url) if url else None

    return url_map


async def _notification_to_response(
    notif,
    db=None,
    emoji_url_map: dict | None = None,
    emoji_cache: dict | None = None,
    actor_id=None,
) -> NotificationResponse:
    account = None
    if notif.sender:
        actor_emojis = await _resolve_actor_emojis(
            db, notif.sender.display_name, notif.sender.domain
        )
        account = NoteActorResponse(
            id=notif.sender.id,
            username=notif.sender.username,
            display_name=notif.sender.display_name,
            avatar_url=(media_proxy_url(notif.sender.avatar_url) or "/default-avatar.svg"),
            ap_id=notif.sender.ap_id,
            domain=notif.sender.domain,
            emojis=actor_emojis,
        )

    status = None
    if notif.note:
        from app.api.mastodon.statuses import note_to_response

        status = await note_to_response(
            notif.note, db=db, emoji_cache=emoji_cache, actor_id=actor_id
        )

    emoji_url = None
    if emoji_url_map and notif.reaction_emoji:
        emoji_url = emoji_url_map.get(notif.reaction_emoji)

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

    # 絵文字URLをバッチ解決
    emoji_strings = [n.reaction_emoji for n in notifications]
    emoji_url_map = await _batch_resolve_emoji_urls(db, emoji_strings)

    # Note用の絵文字キャッシュもバッチ構築
    notes_with_content = [n.note for n in notifications if n.note]
    emoji_cache: dict | None = None
    if notes_with_content:
        from app.api.mastodon.statuses import _build_emoji_cache

        emoji_cache = await _build_emoji_cache(db, notes_with_content)

    result = []
    for n in notifications:
        result.append(
            await _notification_to_response(
                n,
                db=db,
                emoji_url_map=emoji_url_map,
                emoji_cache=emoji_cache,
                actor_id=user.actor_id,
            )
        )
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


@router.post("/mark_all_as_read")
async def mark_all_notifications_as_read(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.notification_service import mark_all_as_read

    await mark_all_as_read(db, user.actor_id)
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
