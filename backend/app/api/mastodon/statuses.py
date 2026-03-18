import logging
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)


def _to_mastodon_datetime(dt: datetime | None) -> str:
    """Format datetime to Mastodon-compatible ISO 8601 string (with Z suffix)."""
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

from app.dependencies import get_current_user, get_db, get_optional_user, get_permitted_staff
from app.schemas.note import ImportReactRequest
from app.models.note import Note
from app.models.user import User
from app.schemas.note import (
    ContextResponse,
    CustomEmojiInfo,
    EmojiReaction,
    NoteActorResponse,
    NoteCreateRequest,
    NoteEditHistoryEntry,
    NoteEditRequest,
    NoteMediaAttachment,
    NoteResponse,
    PollResponse,
    PreviewCardResponse,
    ReactionSummary,
    TagInfo,
)
from app.services.actor_service import actor_uri
from app.services.note_service import (
    _note_load_options,
    check_note_visible,
    create_note,
    get_note_by_id,
    get_reaction_summaries,
    get_reaction_summary,
)
from app.utils.media_proxy import media_proxy_url

_SHORTCODE_RE = re.compile(r":([a-zA-Z0-9_]+):")

router = APIRouter(prefix="/api/v1/statuses", tags=["statuses"])


def _preview_card_to_response(card) -> PreviewCardResponse:
    """Convert a PreviewCard model to a Mastodon-compatible PreviewCardResponse."""
    return PreviewCardResponse(
        url=card.url,
        title=card.title or "",
        description=card.description or "",
        image=card.image,
        type=card.card_type or "link",
        provider_name=card.site_name or "",
    )


def _mime_to_media_type(mime: str) -> str:
    """Convert a MIME type to Mastodon media type string."""
    if mime.startswith("image/gif"):
        return "gifv"
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    return "unknown"


def _attachment_to_media(att) -> NoteMediaAttachment:
    """Convert a NoteAttachment to NoteMediaAttachment for API response."""
    if att.drive_file:
        from app.services.drive_service import file_to_url

        url = file_to_url(att.drive_file)
        mime = att.drive_file.mime_type or ""
        meta = None
        if att.drive_file.width and att.drive_file.height:
            meta = {"original": {"width": att.drive_file.width, "height": att.drive_file.height}}
        if att.drive_file.focal_x is not None and att.drive_file.focal_y is not None:
            if meta is None:
                meta = {}
            meta["focus"] = {"x": att.drive_file.focal_x, "y": att.drive_file.focal_y}
        return NoteMediaAttachment(
            id=str(att.id),
            type=_mime_to_media_type(mime),
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
    if att.remote_focal_x is not None and att.remote_focal_y is not None:
        if meta is None:
            meta = {}
        meta["focus"] = {"x": att.remote_focal_x, "y": att.remote_focal_y}
    proxied = media_proxy_url(att.remote_url)
    preview = media_proxy_url(att.remote_url, variant="preview")
    return NoteMediaAttachment(
        id=str(att.id),
        type=_mime_to_media_type(mime),
        url=proxied,
        preview_url=preview,
        remote_url=att.remote_url,
        description=att.remote_description,
        blurhash=att.remote_blurhash,
        meta=meta,
    )


async def note_to_response(
    note,
    reactions: list[dict] | None = None,
    reblog_note=None,
    db=None,
    emoji_cache: dict | None = None,
    hashtags_cache: dict | None = None,
    actor_id=None,
    reactions_map: dict | None = None,
    reblogged_set: set | None = None,
    software_cache: dict | None = None,
    cards_cache: dict | None = None,
) -> NoteResponse:
    """Convert a Note model to a NoteResponse.

    Args:
        emoji_cache: Optional pre-resolved emoji cache mapping
            (shortcode, domain) -> CustomEmoji. When provided, skips per-note
            emoji DB queries.
        software_cache: Optional mapping domain -> (software_name, version) tuple.
    """
    actor = note.actor
    reblog = None
    # 明示的にreblog_noteが渡されない場合、renote_ofリレーションを使う
    actual_reblog = reblog_note
    if not actual_reblog and hasattr(note, "renote_of") and note.renote_of:
        actual_reblog = note.renote_of
    # Fallback: renote_of not loaded but renote_of_id is set
    if not actual_reblog and db and note.renote_of_id:
        actual_reblog = await get_note_by_id(db, note.renote_of_id)
    # リレーション未解決だがrenote_of_ap_idがある場合、遅延解決
    if not actual_reblog and db and note.renote_of_ap_id:
        from app.services.note_service import fetch_remote_note

        resolved = await fetch_remote_note(db, note.renote_of_ap_id)
        if resolved:
            note.renote_of_id = resolved.id
            await db.commit()
            actual_reblog = await get_note_by_id(db, resolved.id)
    if actual_reblog:
        # リノート元ノートのリアクションを解決
        reblog_reactions = None
        if reactions_map is not None:
            reblog_reactions = reactions_map.get(actual_reblog.id, [])
        elif db:
            reblog_reactions = await get_reaction_summary(
                db, actual_reblog.id, actor_id
            )
        reblog = await note_to_response(
            actual_reblog,
            reactions=reblog_reactions,
            db=db,
            emoji_cache=emoji_cache,
            hashtags_cache=hashtags_cache,
            actor_id=actor_id,
            reactions_map=reactions_map,
            reblogged_set=reblogged_set,
            software_cache=software_cache,
            cards_cache=cards_cache,
        )

    # Build media attachments
    media_attachments = []
    for att in note.attachments or []:
        if att.drive_file or att.remote_url:
            media_attachments.append(_attachment_to_media(att))

    # Build quote
    quote = None
    if hasattr(note, "quoted_note") and note.quoted_note:
        quote = await note_to_response(
            note.quoted_note,
            db=db,
            emoji_cache=emoji_cache,
            hashtags_cache=hashtags_cache,
            actor_id=actor_id,
            reactions_map=reactions_map,
            software_cache=software_cache,
            cards_cache=cards_cache,
        )
    # Fallback: quoted_note not loaded but quote_id is set
    if not quote and db and note.quote_id:
        loaded_quote = await get_note_by_id(db, note.quote_id)
        if loaded_quote:
            quote = await note_to_response(
                loaded_quote,
                db=db,
                emoji_cache=emoji_cache,
                actor_id=actor_id,
                reactions_map=reactions_map,
                software_cache=software_cache,
                cards_cache=cards_cache,
            )
    # 引用もリレーション未解決だがquote_ap_idがある場合、遅延解決
    if not quote and db and note.quote_ap_id:
        from app.services.note_service import fetch_remote_note

        resolved_quote = await fetch_remote_note(db, note.quote_ap_id)
        if resolved_quote:
            note.quote_id = resolved_quote.id
            await db.commit()
            loaded_quote = await get_note_by_id(db, resolved_quote.id)
            if loaded_quote:
                quote = await note_to_response(
                    loaded_quote,
                    db=db,
                    emoji_cache=emoji_cache,
                    hashtags_cache=hashtags_cache,
                    actor_id=actor_id,
                    reactions_map=reactions_map,
                    software_cache=software_cache,
                    cards_cache=cards_cache,
                )

    # Resolve custom emoji from content and display_name
    emojis: list[CustomEmojiInfo] = []
    actor_emojis: list[CustomEmojiInfo] = []
    # Collect shortcodes from note content and actor display_name
    content_shortcodes: set[str] = set()
    if note.content:
        content_shortcodes = set(_SHORTCODE_RE.findall(note.content))
    actor_shortcodes: set[str] = set()
    if actor.display_name:
        actor_shortcodes = set(_SHORTCODE_RE.findall(actor.display_name))
    all_shortcodes = content_shortcodes | actor_shortcodes
    if all_shortcodes:
        if emoji_cache is not None:
            # Use pre-resolved cache — no DB queries needed
            emoji_list = _resolve_emojis_from_cache(
                all_shortcodes,
                actor.domain,
                emoji_cache,
            )
        elif db:
            from app.services.emoji_service import (
                get_emojis_by_shortcodes,
            )

            domain = actor.domain
            emoji_list = await get_emojis_by_shortcodes(
                db,
                all_shortcodes,
                domain,
            )
            if domain is not None:
                found = {e.shortcode for e in emoji_list}
                missing = all_shortcodes - found
                if missing:
                    local_emojis = await get_emojis_by_shortcodes(
                        db,
                        missing,
                        None,
                    )
                    emoji_list.extend(local_emojis)
        else:
            emoji_list = []
        emoji_map: dict[str, CustomEmojiInfo] = {}
        for emoji in emoji_list:
            url = media_proxy_url(emoji.url, variant="emoji")
            static = (
                media_proxy_url(emoji.static_url, variant="emoji", static=True)
                if emoji.static_url
                else media_proxy_url(emoji.url, variant="emoji", static=True)
            )
            info = CustomEmojiInfo(
                shortcode=emoji.shortcode,
                url=url,
                static_url=static,
            )
            emoji_map[emoji.shortcode] = info
        emojis = [emoji_map[sc] for sc in content_shortcodes if sc in emoji_map]
        actor_emojis = [emoji_map[sc] for sc in actor_shortcodes if sc in emoji_map]

    # Resolve hashtags
    tags: list[TagInfo] = []
    if hashtags_cache is not None:
        from app.config import settings as app_settings

        tag_names = hashtags_cache.get(note.id, [])
        tags = [TagInfo(name=tn, url=f"{app_settings.server_url}/tags/{tn}") for tn in tag_names]
    elif db:
        from app.services.hashtag_service import get_hashtags_for_note

        tag_names = await get_hashtags_for_note(db, note.id)
        from app.config import settings as app_settings

        tags = [TagInfo(name=tn, url=f"{app_settings.server_url}/tags/{tn}") for tn in tag_names]

    # Resolve in_reply_to_account_id (prefer eager-loaded relationship)
    in_reply_to_account_id = None
    if note.in_reply_to_id:
        if hasattr(note, "in_reply_to") and note.in_reply_to:
            in_reply_to_account_id = note.in_reply_to.actor_id
        elif db:
            parent_note = await get_note_by_id(db, note.in_reply_to_id)
            if parent_note:
                in_reply_to_account_id = parent_note.actor_id

    edited_at = None
    if note.updated_at:
        edited_at = _to_mastodon_datetime(note.updated_at)

    # Build poll response
    poll_response = None
    if note.is_poll and note.poll_options:
        from app.services.poll_service import get_poll_data

        poll_data = await get_poll_data(db, note.id, actor_id) if db else None
        if poll_data:
            poll_response = PollResponse(**poll_data)

    # favourited判定: リアクション一覧から⭐のmeフラグを確認
    favourited = False
    if reactions:
        for r in reactions:
            if r.get("emoji") == "\u2b50" and r.get("me"):
                favourited = True
                break

    from app.config import settings as app_settings

    avatar = media_proxy_url(actor.avatar_url, variant="avatar") or "/default-avatar.svg"
    header = media_proxy_url(actor.header_url) or ""
    acct = actor.username if not actor.domain else f"{actor.username}@{actor.domain}"
    actor_url = (
        f"{app_settings.server_url}/@{actor.username}"
        if not actor.domain
        else f"{app_settings.server_url}/@{acct}"
    )
    # Resolve server software from cache or Valkey
    sw = None
    sw_ver = None
    if actor.domain:
        if software_cache is not None:
            cached = software_cache.get(actor.domain)
            if cached is not None:
                sw, sw_ver = cached
        elif db:
            from app.utils.nodeinfo import get_domain_software_info
            sw, sw_ver = await get_domain_software_info(actor.domain)

    actor_resp = NoteActorResponse(
        id=actor.id,
        username=actor.username,
        display_name=actor.display_name or "",
        avatar_url=avatar,
        ap_id=actor.ap_id,
        domain=actor.domain,
        server_software=sw,
        server_software_version=sw_ver,
        emojis=actor_emojis,
        acct=acct,
        uri=actor.ap_id,
        url=actor_url,
        avatar=avatar,
        avatar_static=avatar,
        header=header,
        header_static=header,
        note=actor.summary or "",
        bot=actor.is_bot,
        group=actor.type == "Group",
        created_at=_to_mastodon_datetime(actor.created_at),
        locked=actor.manually_approves_followers,
        discoverable=actor.discoverable,
    )

    # Resolve preview card
    card_resp = None
    if cards_cache is not None:
        card_obj = cards_cache.get(note.id)
        if card_obj:
            card_resp = _preview_card_to_response(card_obj)
    elif db:
        from app.models.preview_card import PreviewCard

        card_result = await db.execute(
            select(PreviewCard).where(PreviewCard.note_id == note.id)
        )
        card_obj = card_result.scalar_one_or_none()
        if card_obj:
            card_resp = _preview_card_to_response(card_obj)

    return NoteResponse(
        id=note.id,
        ap_id=note.ap_id,
        content=note.content,
        source=note.source,
        visibility="private" if note.visibility == "followers" else note.visibility,
        sensitive=note.sensitive,
        spoiler_text=note.spoiler_text or "",
        published=_to_mastodon_datetime(note.published),
        edited_at=edited_at,
        replies_count=note.replies_count,
        reactions_count=note.reactions_count,
        renotes_count=note.renotes_count,
        in_reply_to_id=note.in_reply_to_id,
        in_reply_to_account_id=in_reply_to_account_id,
        actor=actor_resp,
        reactions=[ReactionSummary(**r) for r in (reactions or [])],
        emoji_reactions=[
            EmojiReaction(
                name=r["emoji"],
                count=r["count"],
                me=r.get("me", False),
                url=r.get("emoji_url"),
                static_url=r.get("emoji_url"),
                account_ids=r.get("account_ids", []),
            )
            for r in (reactions or [])
        ],
        favourited=favourited,
        reblogged=bool(reblogged_set and note.id in reblogged_set),
        reblog=reblog,
        media_attachments=media_attachments,
        quote=quote,
        poll=poll_response,
        emojis=emojis,
        tags=tags,
        card=card_resp,
        # Mastodon Status compat
        uri=note.ap_id,
        url=f"{app_settings.server_url}/notes/{note.id}",
        account=actor_resp,
        created_at=_to_mastodon_datetime(note.published),
        reblogs_count=note.renotes_count,
        favourites_count=note.reactions_count,
    )


def _resolve_emojis_from_cache(
    shortcodes: set[str],
    domain: str | None,
    emoji_cache: dict,
) -> list:
    """Resolve emoji shortcodes using a pre-built cache dict.

    The cache maps (shortcode, domain) -> CustomEmoji object.
    Tries the note's actor domain first, then falls back to local (None).
    """
    result = []
    for sc in shortcodes:
        emoji = emoji_cache.get((sc, domain))
        if not emoji:
            emoji = emoji_cache.get((sc, None))
        if emoji:
            result.append(emoji)
    return result


async def _build_emoji_cache(db, notes) -> dict:
    """Pre-fetch all custom emoji needed for a list of notes.

    Collects shortcodes from note content (and reblog/quote content),
    then batch-fetches all matching emoji in minimal DB queries.

    Returns a dict mapping (shortcode, domain) -> CustomEmoji.
    """
    from app.services.emoji_service import get_emojis_by_shortcodes

    # Collect all (shortcodes, domain) pairs needed
    shortcodes_by_domain: dict[str | None, set[str]] = {}

    def _collect(note):
        if not note:
            return
        scs = set()
        if note.content:
            scs.update(_SHORTCODE_RE.findall(note.content))
        if note.actor and note.actor.display_name:
            scs.update(_SHORTCODE_RE.findall(note.actor.display_name))
        if scs:
            d = note.actor.domain if note.actor else None
            shortcodes_by_domain.setdefault(d, set()).update(scs)
            shortcodes_by_domain.setdefault(None, set()).update(scs)

    for n in notes:
        _collect(n)
        if hasattr(n, "renote_of") and n.renote_of:
            _collect(n.renote_of)
        if hasattr(n, "quoted_note") and n.quoted_note:
            _collect(n.quoted_note)

    # Batch fetch per domain (typically 1-3 queries total)
    cache: dict[tuple[str, str | None], object] = {}
    for domain, scs in shortcodes_by_domain.items():
        if not scs:
            continue
        emoji_list = await get_emojis_by_shortcodes(db, scs, domain)
        for e in emoji_list:
            cache[(e.shortcode, e.domain)] = e

    return cache


async def notes_to_responses(
    notes,
    reactions_map: dict,
    db,
    actor_id=None,
) -> list[NoteResponse]:
    """Convert multiple notes to responses with batched emoji/hashtag resolution.

    Args:
        notes: List of Note model objects.
        reactions_map: Dict mapping note_id -> list of reaction summary dicts,
            as returned by get_reaction_summaries().
        db: AsyncSession.
        actor_id: Optional current user's actor ID for reaction "me" flags.

    Returns:
        List of NoteResponse in the same order as input notes.
    """
    from app.services.hashtag_service import get_hashtags_for_notes

    emoji_cache = await _build_emoji_cache(db, notes)

    # Batch-fetch hashtags for all notes (including renote/quote targets)
    all_note_ids: list = [n.id for n in notes]
    for n in notes:
        if hasattr(n, "renote_of") and n.renote_of:
            all_note_ids.append(n.renote_of.id)
            if hasattr(n.renote_of, "quoted_note") and n.renote_of.quoted_note:
                all_note_ids.append(n.renote_of.quoted_note.id)
        if hasattr(n, "quoted_note") and n.quoted_note:
            all_note_ids.append(n.quoted_note.id)
    # Deduplicate while preserving order
    seen_ids: set = set()
    unique_ids = []
    for nid in all_note_ids:
        if nid not in seen_ids:
            seen_ids.add(nid)
            unique_ids.append(nid)
    hashtags_cache = await get_hashtags_for_notes(db, unique_ids)

    # リノート/引用ノートのリアクションもバッチ取得
    inner_ids = [
        nid for nid in unique_ids if nid not in reactions_map
    ]
    if inner_ids:
        inner_reactions = await get_reaction_summaries(db, inner_ids, actor_id)
        reactions_map.update(inner_reactions)

    # Batch-check which notes the current user has reblogged
    reblogged_set: set = set()
    if actor_id:
        from app.models.note import Note as NoteModel

        reblog_result = await db.execute(
            select(NoteModel.renote_of_id).where(
                NoteModel.actor_id == actor_id,
                NoteModel.renote_of_id.in_(unique_ids),
                NoteModel.deleted_at.is_(None),
            )
        )
        reblogged_set = {row[0] for row in reblog_result.all()}

    # Batch-fetch server software for all unique remote domains
    from app.utils.nodeinfo import get_domain_software_info

    domains: set[str] = set()
    for n in notes:
        if n.actor.domain:
            domains.add(n.actor.domain)
        if hasattr(n, "renote_of") and n.renote_of and n.renote_of.actor.domain:
            domains.add(n.renote_of.actor.domain)
        if hasattr(n, "quoted_note") and n.quoted_note and n.quoted_note.actor.domain:
            domains.add(n.quoted_note.actor.domain)
    software_cache: dict[str, tuple[str | None, str | None]] = {}
    for domain in domains:
        software_cache[domain] = await get_domain_software_info(domain)

    # Batch-fetch preview cards for all notes
    from app.models.preview_card import PreviewCard

    cards_result = await db.execute(
        select(PreviewCard).where(PreviewCard.note_id.in_(unique_ids))
    )
    cards_cache: dict = {c.note_id: c for c in cards_result.scalars().all()}

    result = []
    for n in notes:
        reactions = reactions_map.get(n.id, [])
        resp = await note_to_response(
            n,
            reactions,
            db=db,
            emoji_cache=emoji_cache,
            hashtags_cache=hashtags_cache,
            actor_id=actor_id,
            reactions_map=reactions_map,
            reblogged_set=reblogged_set,
            software_cache=software_cache,
            cards_cache=cards_cache,
        )
        result.append(resp)
    return result


@router.post("", response_model=NoteResponse, status_code=201)
async def create_status(
    body: NoteCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Validate in_reply_to_id exists
    if body.in_reply_to_id:
        parent = await get_note_by_id(db, body.in_reply_to_id)
        if not parent:
            raise HTTPException(status_code=404, detail="Reply target not found")

    poll_options = None
    poll_expires_in = None
    poll_multiple = False
    if body.poll:
        poll_options = body.poll.options
        poll_expires_in = body.poll.expires_in
        poll_multiple = body.poll.multiple

    try:
        note = await create_note(
            db=db,
            user=user,
            content=body.content,
            visibility="followers" if body.visibility == "private" else body.visibility,
            sensitive=body.sensitive,
            spoiler_text=body.spoiler_text,
            in_reply_to_id=body.in_reply_to_id,
            media_ids=body.media_ids or None,
            quote_id=body.quote_id,
            poll_options=poll_options,
            poll_expires_in=poll_expires_in,
            poll_multiple=poll_multiple,
        )
    except Exception as e:
        logger.exception("Failed to create note")
        raise HTTPException(status_code=422, detail=str(e))
    return await note_to_response(note, db=db)


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
    return await note_to_response(note, reactions, db=db, actor_id=actor_id)


@router.put("/{note_id}", response_model=NoteResponse)
async def edit_status(
    note_id: uuid.UUID,
    body: NoteEditRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    note = await get_note_by_id(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    if note.actor_id != user.actor_id:
        raise HTTPException(status_code=403, detail="Not your note")

    # Save current state as edit history
    from app.models.note_edit import NoteEdit

    edit_record = NoteEdit(
        note_id=note.id,
        content=note.content,
        source=note.source,
        spoiler_text=note.spoiler_text or "",
    )
    db.add(edit_record)

    # Update the note
    from app.utils.sanitize import text_to_html

    note.content = text_to_html(body.content)
    note.source = body.content
    note.spoiler_text = body.spoiler_text
    note.updated_at = datetime.now(timezone.utc)
    await db.commit()

    # Deliver AP Update to followers
    from app.activitypub.renderer import render_note, render_update_activity
    from app.services.delivery_service import enqueue_delivery
    from app.services.follow_service import get_follower_inboxes

    actor = user.actor
    note_data = render_note(note)
    update_activity = render_update_activity(
        activity_id=f"{note.ap_id}/update/{int(note.updated_at.timestamp())}",
        actor_ap_id=actor_uri(actor),
        object_data=note_data,
    )
    inboxes = await get_follower_inboxes(db, actor.id)
    for inbox_url in inboxes:
        await enqueue_delivery(db, actor.id, inbox_url, update_activity)

    # Reload note for response
    note = await get_note_by_id(db, note_id)
    return await note_to_response(note, db=db)


@router.get("/{note_id}/history", response_model=list[NoteEditHistoryEntry])
async def get_status_history(
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

    from app.models.note_edit import NoteEdit

    result = await db.execute(
        select(NoteEdit).where(NoteEdit.note_id == note.id).order_by(NoteEdit.created_at.asc())
    )
    edits = result.scalars().all()

    # Build history: past edits + current state
    history = [
        NoteEditHistoryEntry(
            content=e.content,
            source=e.source,
            spoiler_text=e.spoiler_text,
            created_at=e.created_at,
        )
        for e in edits
    ]
    # Append current version
    history.append(
        NoteEditHistoryEntry(
            content=note.content,
            source=note.source,
            spoiler_text=note.spoiler_text or "",
            created_at=note.updated_at or note.published,
        )
    )
    return history


@router.get("/{note_id}/context", response_model=ContextResponse)
async def get_status_context(
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

    # 祖先ノードのIDを先に収集してバッチ取得
    MAX_ANCESTORS = 40
    MAX_DESCENDANTS = 200
    ancestor_ids: list[uuid.UUID] = []
    current = note
    seen_ids: set[uuid.UUID] = {note.id}
    while (
        current.in_reply_to_id
        and current.in_reply_to_id not in seen_ids
        and len(ancestor_ids) < MAX_ANCESTORS
    ):
        parent = await get_note_by_id(db, current.in_reply_to_id)
        if not parent:
            break
        if not await check_note_visible(db, parent, actor_id):
            break
        seen_ids.add(parent.id)
        ancestor_ids.append(parent.id)
        current = parent
    ancestor_ids.reverse()

    # バッチ取得した祖先をID順で復元
    ancestors = []
    if ancestor_ids:
        result = await db.execute(
            select(Note)
            .options(*_note_load_options())
            .where(Note.id.in_(ancestor_ids), Note.deleted_at.is_(None))
        )
        ancestor_map = {n.id: n for n in result.scalars().all()}
        ancestors = [ancestor_map[aid] for aid in ancestor_ids if aid in ancestor_map]

    # 子孫ノードをBFSで取得(深さ/件数制限付き)
    descendants = []
    queue = [note.id]
    visited: set[uuid.UUID] = {note.id}
    while queue and len(descendants) < MAX_DESCENDANTS:
        batch_parent_ids = queue[:50]
        queue = queue[50:]
        result = await db.execute(
            select(Note)
            .options(*_note_load_options())
            .where(
                Note.in_reply_to_id.in_(batch_parent_ids),
                Note.deleted_at.is_(None),
            )
            .order_by(Note.published.asc())
        )
        children = list(result.scalars().all())
        for child in children:
            if child.id in visited:
                continue
            visited.add(child.id)
            if len(descendants) >= MAX_DESCENDANTS:
                break
            if await check_note_visible(db, child, actor_id):
                descendants.append(child)
                queue.append(child.id)

    # バッチで絵文字キャッシュを構築
    all_context_notes = ancestors + descendants
    emoji_cache = await _build_emoji_cache(db, all_context_notes) if all_context_notes else {}

    ancestor_responses = [
        await note_to_response(n, db=db, emoji_cache=emoji_cache, actor_id=actor_id)
        for n in ancestors
    ]
    descendant_responses = [
        await note_to_response(n, db=db, emoji_cache=emoji_cache, actor_id=actor_id)
        for n in descendants
    ]

    return ContextResponse(
        ancestors=ancestor_responses,
        descendants=descendant_responses,
    )


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
        from app.services.notification_service import create_notification, publish_notification

        notif = await create_notification(
            db,
            "reaction",
            note.actor_id,
            user.actor_id,
            note.id,
            reaction_emoji=emoji,
        )
        await db.commit()
        if notif:
            await publish_notification(notif)

    return {"ok": True}


@router.post("/{note_id}/import-react")
async def import_and_react(
    note_id: uuid.UUID,
    body: ImportReactRequest,
    user: User = Depends(get_permitted_staff("emoji")),
    db: AsyncSession = Depends(get_db),
):
    """Import a remote custom emoji to local and react with it."""
    from app.services.emoji_service import (
        get_custom_emoji,
        import_remote_emoji_to_local,
        update_emoji,
    )
    from app.services.reaction_service import add_reaction

    # Parse emoji string
    m = re.match(r"^:([a-zA-Z0-9_]+)@([a-zA-Z0-9.-]+):$", body.emoji)
    if not m:
        raise HTTPException(status_code=422, detail="Invalid remote emoji format")
    shortcode, domain = m.group(1), m.group(2)

    note = await get_note_by_id(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    # Check if already local
    local_emoji = await get_custom_emoji(db, shortcode, None)
    if not local_emoji:
        # Find remote emoji
        remote_emoji = await get_custom_emoji(db, shortcode, domain)
        if not remote_emoji:
            raise HTTPException(status_code=404, detail="Remote emoji not found")

        # Apply metadata overrides before import
        overrides = {}
        if body.category is not None:
            overrides["category"] = body.category
        if body.author is not None:
            overrides["author"] = body.author
        if body.license is not None:
            overrides["license"] = body.license
        if body.description is not None:
            overrides["description"] = body.description
        if body.is_sensitive is not None:
            overrides["is_sensitive"] = body.is_sensitive
        if body.aliases is not None:
            overrides["aliases"] = body.aliases
        if overrides:
            await update_emoji(db, remote_emoji.id, overrides)

        try:
            local_emoji = await import_remote_emoji_to_local(db, remote_emoji.id)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        # Apply shortcode override to the new local emoji
        if body.shortcode and body.shortcode != shortcode:
            await update_emoji(db, local_emoji.id, {"shortcode": body.shortcode})
            shortcode = body.shortcode

        await db.commit()

    # React with local emoji (optional)
    if body.react:
        local_emoji_str = f":{shortcode}:"
        try:
            await add_reaction(db, user, note, local_emoji_str)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        # Notify note author
        if note.actor.is_local:
            from app.services.notification_service import (
                create_notification,
                publish_notification,
            )

            notif = await create_notification(
                db,
                "reaction",
                note.actor_id,
                user.actor_id,
                note.id,
                reaction_emoji=local_emoji_str,
            )
            await db.commit()
            if notif:
                await publish_notification(notif)

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


@router.put("/{note_id}/emoji_reactions/{emoji}", response_model=NoteResponse)
async def fedibird_react(
    note_id: uuid.UUID,
    emoji: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fedibird-compatible: add emoji reaction and return updated status."""
    from app.services.reaction_service import add_reaction

    note = await get_note_by_id(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    if not await check_note_visible(db, note, user.actor_id):
        raise HTTPException(status_code=404, detail="Note not found")

    try:
        await add_reaction(db, user, note, emoji)
    except ValueError:
        pass  # Already reacted — return current status

    if note.actor.is_local and note.actor_id != user.actor_id:
        from app.services.notification_service import create_notification, publish_notification

        notif = await create_notification(
            db, "reaction", note.actor_id, user.actor_id, note.id, reaction_emoji=emoji
        )
        await db.commit()
        if notif:
            await publish_notification(notif)

    note = await get_note_by_id(db, note_id)
    reactions_map = await get_reaction_summaries(
        db, [note.id], user.actor_id, include_account_ids=True
    )
    return await note_to_response(
        note, reactions_map.get(note.id, []), db=db, actor_id=user.actor_id
    )


@router.delete("/{note_id}/emoji_reactions/{emoji}", response_model=NoteResponse)
async def fedibird_unreact(
    note_id: uuid.UUID,
    emoji: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fedibird-compatible: remove emoji reaction and return updated status."""
    from app.services.reaction_service import remove_reaction

    note = await get_note_by_id(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    if not await check_note_visible(db, note, user.actor_id):
        raise HTTPException(status_code=404, detail="Note not found")

    try:
        await remove_reaction(db, user, note, emoji)
    except ValueError:
        pass  # Not reacted — return current status

    note = await get_note_by_id(db, note_id)
    reactions_map = await get_reaction_summaries(
        db, [note.id], user.actor_id, include_account_ids=True
    )
    return await note_to_response(
        note, reactions_map.get(note.id, []), db=db, actor_id=user.actor_id
    )


@router.post("/{note_id}/favourite", response_model=NoteResponse)
async def favourite_status(
    note_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Favourite a status (alias for ⭐ reaction)."""
    from app.services.reaction_service import add_reaction

    note = await get_note_by_id(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    if not await check_note_visible(db, note, user.actor_id):
        raise HTTPException(status_code=404, detail="Note not found")

    try:
        await add_reaction(db, user, note, "\u2b50")
    except ValueError:
        pass  # 既にリアクション済みの場合は無視（通知は作成しない）
    else:
        # 通知作成 (新規リアクション成功時、ローカルユーザーの場合のみ)
        if note.actor.is_local and note.actor_id != user.actor_id:
            from app.services.notification_service import create_notification, publish_notification

            notif = await create_notification(
                db, "reaction", note.actor_id, user.actor_id, note.id, reaction_emoji="\u2b50"
            )
            await db.commit()
            if notif:
                await publish_notification(notif)

    note = await get_note_by_id(db, note_id)
    reactions = await get_reaction_summary(db, note.id, user.actor_id)
    return await note_to_response(note, reactions, db=db, actor_id=user.actor_id)


@router.post("/{note_id}/unfavourite", response_model=NoteResponse)
async def unfavourite_status(
    note_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Unfavourite a status (remove ⭐ reaction)."""
    from app.services.reaction_service import remove_reaction

    note = await get_note_by_id(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    if not await check_note_visible(db, note, user.actor_id):
        raise HTTPException(status_code=404, detail="Note not found")

    try:
        await remove_reaction(db, user, note, "\u2b50")
    except ValueError:
        pass  # リアクションが存在しない場合は無視

    note = await get_note_by_id(db, note_id)
    reactions = await get_reaction_summary(db, note.id, user.actor_id)
    return await note_to_response(note, reactions, db=db, actor_id=user.actor_id)


@router.get("/{note_id}/favourited_by")
async def favourited_by(
    note_id: uuid.UUID,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """List accounts that favourited (⭐ reacted) a status."""
    from app.api.mastodon.accounts import _actor_to_account
    from app.models.reaction import Reaction

    note = await get_note_by_id(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    actor_id = user.actor_id if user else None
    if not await check_note_visible(db, note, actor_id):
        raise HTTPException(status_code=404, detail="Note not found")

    result = await db.execute(
        select(Reaction)
        .options(selectinload(Reaction.actor))
        .where(Reaction.note_id == note.id, Reaction.emoji == "\u2b50")
        .order_by(Reaction.created_at.desc())
        .limit(80)
    )
    reactions = result.scalars().all()

    return [await _actor_to_account(r.actor, db=db) for r in reactions]


@router.get("/{note_id}/reacted_by")
async def reacted_by(
    note_id: uuid.UUID,
    emoji: str | None = None,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.reaction import Reaction

    note = await get_note_by_id(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    actor_id = user.actor_id if user else None
    if not await check_note_visible(db, note, actor_id):
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

    # Batch-collect all shortcodes from reactor display names
    from app.services.emoji_service import get_emojis_by_shortcodes

    all_shortcodes_by_domain: dict[str | None, set[str]] = {}
    for r in reactions:
        if r.actor.display_name:
            scs = set(_SHORTCODE_RE.findall(r.actor.display_name))
            if scs:
                domain = r.actor.domain
                all_shortcodes_by_domain.setdefault(domain, set()).update(scs)
                all_shortcodes_by_domain.setdefault(None, set()).update(scs)

    # Batch-fetch emojis per domain
    emoji_cache: dict[tuple[str, str | None], object] = {}
    for domain, scs in all_shortcodes_by_domain.items():
        if scs:
            emoji_list = await get_emojis_by_shortcodes(db, scs, domain)
            for e in emoji_list:
                emoji_cache[(e.shortcode, e.domain)] = e

    response = []
    for r in reactions:
        actor_emojis: list[CustomEmojiInfo] = []
        if r.actor.display_name:
            scs = set(_SHORTCODE_RE.findall(r.actor.display_name))
            for sc in scs:
                emoji = emoji_cache.get((sc, r.actor.domain)) or emoji_cache.get((sc, None))
                if emoji:
                    url = media_proxy_url(emoji.url, variant="emoji")
                    static = (
                        media_proxy_url(emoji.static_url, variant="emoji", static=True)
                        if emoji.static_url
                        else media_proxy_url(emoji.url, variant="emoji", static=True)
                    )
                    actor_emojis.append(
                        CustomEmojiInfo(shortcode=emoji.shortcode, url=url, static_url=static)
                    )

        response.append({
            "actor": NoteActorResponse(
                id=r.actor.id,
                username=r.actor.username,
                display_name=r.actor.display_name,
                avatar_url=media_proxy_url(r.actor.avatar_url, variant="avatar") or "/default-avatar.svg",
                ap_id=r.actor.ap_id,
                domain=r.actor.domain,
                emojis=actor_emojis,
            ),
            "emoji": r.emoji,
        })
    return response


@router.post("/{note_id}/reblog", response_model=NoteResponse, status_code=200)
async def reblog_status(
    note_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    original = await get_note_by_id(db, note_id)
    if not original:
        raise HTTPException(status_code=404, detail="Note not found")

    # Reject reblog for non-public/unlisted notes (followers-only, direct)
    if original.visibility in ("followers", "direct"):
        raise HTTPException(
            status_code=422,
            detail="Cannot reblog a private post",
        )

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
        from app.services.notification_service import create_notification, publish_notification

        notif = await create_notification(
            db,
            "renote",
            original.actor_id,
            actor.id,
            original.id,
        )
        await db.commit()
        if notif:
            await publish_notification(notif)

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
        published=_to_mastodon_datetime(reblog_note.published),
    )
    inboxes = await get_follower_inboxes(db, actor.id)
    for inbox_url in inboxes:
        await enqueue_delivery(db, actor.id, inbox_url, activity)

    # Publish streaming events so followers see the reblog in real-time
    try:
        import json as _json

        from app.services.follow_service import get_follower_ids
        from app.valkey_client import valkey as valkey_client

        event = _json.dumps({"event": "update", "payload": {"id": str(reblog_note.id)}})
        await valkey_client.publish("timeline:public", event)
        follower_ids = await get_follower_ids(db, actor.id)
        for fid in follower_ids:
            await valkey_client.publish(f"timeline:home:{fid}", event)
        await valkey_client.publish(f"timeline:home:{actor.id}", event)
    except Exception:
        pass  # Don't fail reblog if pub/sub fails

    # Re-refresh after delivery commits expired the session
    await db.refresh(reblog_note, ["actor", "attachments"])
    await db.refresh(original, ["actor", "attachments"])
    return await note_to_response(reblog_note, reblog_note=original, db=db)


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
        published=_to_mastodon_datetime(reblog_note.published),
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
