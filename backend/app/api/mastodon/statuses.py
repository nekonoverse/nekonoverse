import logging
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)


def _to_mastodon_datetime(dt: datetime | None) -> str:
    """datetime を Mastodon 互換の ISO 8601 文字列（Z サフィックス付き）にフォーマットする。"""
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


from app.dependencies import get_current_user, get_db, get_optional_user, require_oauth_scope
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
    """PreviewCard モデルを Mastodon 互換の PreviewCardResponse に変換する。"""
    return PreviewCardResponse(
        url=card.url,
        title=card.title or "",
        description=card.description or "",
        image=card.image,
        type=card.card_type or "link",
        provider_name=card.site_name or "",
    )


def _mime_to_media_type(mime: str) -> str:
    """MIME タイプを Mastodon のメディアタイプ文字列に変換する。"""
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
    """NoteAttachment を API レスポンス用の NoteMediaAttachment に変換する。"""
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
        if att.drive_file.vision_tags or att.drive_file.vision_caption:
            if meta is None:
                meta = {}
            meta["vision"] = {}
            if att.drive_file.vision_tags:
                meta["vision"]["tags"] = att.drive_file.vision_tags
            if att.drive_file.vision_caption:
                meta["vision"]["caption"] = att.drive_file.vision_caption
        return NoteMediaAttachment(
            id=str(att.id),
            type=_mime_to_media_type(mime),
            url=url,
            preview_url=url,
            description=att.drive_file.description,
            blurhash=att.drive_file.blurhash,
            meta=meta,
        )
    # リモート添付ファイル
    mime = att.remote_mime_type or ""
    meta = None
    if att.remote_width and att.remote_height:
        meta = {"original": {"width": att.remote_width, "height": att.remote_height}}
    if att.remote_focal_x is not None and att.remote_focal_y is not None:
        if meta is None:
            meta = {}
        meta["focus"] = {"x": att.remote_focal_x, "y": att.remote_focal_y}
    if att.remote_vision_tags or att.remote_vision_caption:
        if meta is None:
            meta = {}
        meta["vision"] = {}
        if att.remote_vision_tags:
            meta["vision"]["tags"] = att.remote_vision_tags
        if att.remote_vision_caption:
            meta["vision"]["caption"] = att.remote_vision_caption
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
    pinned: bool = False,
) -> NoteResponse:
    """Note モデルを NoteResponse に変換する。

    Args:
        emoji_cache: 事前に解決した絵文字キャッシュの辞書
            (shortcode, domain) -> CustomEmoji。指定時はノートごとの
            絵文字 DB クエリをスキップする。
        software_cache: domain -> (software_name, version) タプルの辞書。
    """
    actor = note.actor
    reblog = None
    # 明示的にreblog_noteが渡されない場合、renote_ofリレーションを使う
    actual_reblog = reblog_note
    if not actual_reblog and hasattr(note, "renote_of") and note.renote_of:
        actual_reblog = note.renote_of
    # フォールバック: renote_of が未ロードだが renote_of_id が設定されている場合
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
            reblog_reactions = await get_reaction_summary(db, actual_reblog.id, actor_id)
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

    # メディア添付を構築
    media_attachments = []
    for att in note.attachments or []:
        if att.drive_file or att.remote_url:
            media_attachments.append(_attachment_to_media(att))

    # 引用を構築
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
    # フォールバック: quoted_note が未ロードだが quote_id が設定されている場合
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

    # content と display_name からカスタム絵文字を解決
    emojis: list[CustomEmojiInfo] = []
    actor_emojis: list[CustomEmojiInfo] = []
    # ノートの content と アクターの display_name からショートコードを収集
    content_shortcodes: set[str] = set()
    if note.content:
        content_shortcodes = set(_SHORTCODE_RE.findall(note.content))
    actor_shortcodes: set[str] = set()
    if actor.display_name:
        actor_shortcodes = set(_SHORTCODE_RE.findall(actor.display_name))
    all_shortcodes = content_shortcodes | actor_shortcodes
    if all_shortcodes:
        if emoji_cache is not None:
            # 事前解決済みキャッシュを使用 — DB クエリ不要
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

    # ハッシュタグを解決
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

    # in_reply_to_account_id とメンションを解決（eager-loaded リレーションを優先）
    in_reply_to_account_id = None
    reply_mention: dict | None = None
    if note.in_reply_to_id:
        parent_actor = None
        if hasattr(note, "in_reply_to") and note.in_reply_to:
            in_reply_to_account_id = note.in_reply_to.actor_id
            parent_actor = note.in_reply_to.actor
        elif db:
            parent_note = await get_note_by_id(db, note.in_reply_to_id)
            if parent_note:
                in_reply_to_account_id = parent_note.actor_id
                parent_actor = parent_note.actor
        if parent_actor:
            acct = (
                parent_actor.username
                if not parent_actor.domain
                else f"{parent_actor.username}@{parent_actor.domain}"
            )
            reply_mention = {
                "id": str(parent_actor.id),
                "username": parent_actor.username,
                "acct": acct,
                "url": parent_actor.ap_id,
            }

    edited_at = None
    if note.updated_at:
        edited_at = _to_mastodon_datetime(note.updated_at)

    # 投票レスポンスを構築
    poll_response = None
    if note.is_poll and note.poll_options:
        from app.services.poll_service import get_poll_data

        poll_data = await get_poll_data(db, note.id, actor_id) if db else None
        if poll_data:
            poll_response = PollResponse(**poll_data)

    # favourited判定 + favourites_count: ⭐のみ集計
    favourited = False
    favourites_count = 0
    if reactions:
        for r in reactions:
            if r.get("emoji") == "\u2b50":
                favourites_count = r.get("count", 0)
                if r.get("me"):
                    favourited = True
                break

    from app.config import settings as app_settings

    avatar = (
        media_proxy_url(actor.avatar_url, variant="avatar")
        or f"{app_settings.server_url}/default-avatar.svg"
    )
    header = media_proxy_url(actor.header_url) or ""
    acct = actor.username if not actor.domain else f"{actor.username}@{actor.domain}"
    actor_url = (
        f"{app_settings.server_url}/@{actor.username}"
        if not actor.domain
        else f"{app_settings.server_url}/@{acct}"
    )
    # サーバーソフトウェア情報をキャッシュまたは Valkey から解決
    sw = None
    sw_ver = None
    sw_name = None
    if actor.domain:
        if software_cache is not None:
            cached = software_cache.get(actor.domain)
            if cached is not None:
                sw, sw_ver, sw_name = cached
        elif db:
            from app.utils.nodeinfo import get_domain_software_info

            sw, sw_ver, sw_name = await get_domain_software_info(actor.domain)

    actor_resp = NoteActorResponse(
        id=actor.id,
        username=actor.username,
        display_name=actor.display_name or "",
        avatar_url=avatar,
        ap_id=actor.ap_id,
        domain=actor.domain,
        server_software=sw,
        server_software_version=sw_ver,
        server_name=sw_name,
        emojis=actor_emojis,
        acct=acct,
        uri=actor.ap_id,
        url=actor_url,
        avatar=avatar,
        avatar_static=avatar,
        header=header,
        header_static=header,
        note=actor.summary or "",
        is_cat=actor.is_cat,
        bot=actor.is_bot,
        group=actor.type == "Group",
        created_at=_to_mastodon_datetime(actor.created_at),
        locked=actor.manually_approves_followers,
        discoverable=actor.discoverable,
    )

    # プレビューカードを解決
    card_resp = None
    if cards_cache is not None:
        card_obj = cards_cache.get(note.id)
        if card_obj:
            card_resp = _preview_card_to_response(card_obj)
    elif db:
        from app.models.preview_card import PreviewCard

        card_result = await db.execute(select(PreviewCard).where(PreviewCard.note_id == note.id))
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
        pinned=pinned,
        reblog=reblog,
        media_attachments=media_attachments,
        quote=quote,
        poll=poll_response,
        emojis=emojis,
        tags=tags,
        card=card_resp,
        mentions=[reply_mention] if reply_mention else [],
        # Mastodon Status 互換フィールド
        uri=note.ap_id,
        url=f"{app_settings.server_url}/notes/{note.id}",
        account=actor_resp,
        created_at=_to_mastodon_datetime(note.published),
        reblogs_count=note.renotes_count,
        favourites_count=favourites_count,
    )


def _resolve_emojis_from_cache(
    shortcodes: set[str],
    domain: str | None,
    emoji_cache: dict,
) -> list:
    """事前構築したキャッシュ辞書を使って絵文字ショートコードを解決する。

    キャッシュは (shortcode, domain) -> CustomEmoji オブジェクトのマッピング。
    まずノートのアクタードメインを試し、見つからなければローカル (None) にフォールバックする。
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
    """ノートリストに必要な全カスタム絵文字を事前取得する。

    ノートの content（およびリブログ/引用の content）からショートコードを収集し、
    最小限の DB クエリで一致する絵文字をバッチ取得する。

    (shortcode, domain) -> CustomEmoji の辞書を返す。
    """
    from app.services.emoji_service import get_emojis_by_shortcodes

    # 必要な (shortcodes, domain) ペアを全て収集
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

    # ドメインごとにバッチ取得（通常合計1〜3クエリ）
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
    pinned_ids: set | None = None,
) -> list[NoteResponse]:
    """複数ノートをバッチ絵文字/ハッシュタグ解決付きでレスポンスに変換する。

    Args:
        notes: Note モデルオブジェクトのリスト。
        reactions_map: note_id -> リアクションサマリ辞書リストのマッピング。
            get_reaction_summaries() の戻り値形式。
        db: AsyncSession。
        actor_id: リアクションの "me" フラグ用の現在のユーザーのアクター ID（任意）。

    Returns:
        入力ノートと同じ順序の NoteResponse リスト。
    """
    from app.services.hashtag_service import get_hashtags_for_notes

    emoji_cache = await _build_emoji_cache(db, notes)

    # 全ノート（リノート/引用ノート含む）のハッシュタグをバッチ取得
    all_note_ids: list = [n.id for n in notes]
    for n in notes:
        if hasattr(n, "renote_of") and n.renote_of:
            all_note_ids.append(n.renote_of.id)
            if hasattr(n.renote_of, "quoted_note") and n.renote_of.quoted_note:
                all_note_ids.append(n.renote_of.quoted_note.id)
        if hasattr(n, "quoted_note") and n.quoted_note:
            all_note_ids.append(n.quoted_note.id)
    # 順序を保持しつつ重複排除
    seen_ids: set = set()
    unique_ids = []
    for nid in all_note_ids:
        if nid not in seen_ids:
            seen_ids.add(nid)
            unique_ids.append(nid)
    hashtags_cache = await get_hashtags_for_notes(db, unique_ids)

    # リノート/引用ノートのリアクションもバッチ取得
    inner_ids = [nid for nid in unique_ids if nid not in reactions_map]
    if inner_ids:
        inner_reactions = await get_reaction_summaries(db, inner_ids, actor_id)
        reactions_map.update(inner_reactions)

    # 現在のユーザーがリブログ済みのノートをバッチチェック
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

    # 全ユニークリモートドメインのサーバーソフトウェアをバッチ取得
    from app.utils.nodeinfo import get_domain_software_info

    domains: set[str] = set()
    for n in notes:
        if n.actor.domain:
            domains.add(n.actor.domain)
        if hasattr(n, "renote_of") and n.renote_of and n.renote_of.actor.domain:
            domains.add(n.renote_of.actor.domain)
        if hasattr(n, "quoted_note") and n.quoted_note and n.quoted_note.actor.domain:
            domains.add(n.quoted_note.actor.domain)
    software_cache: dict[str, tuple[str | None, str | None, str | None]] = {}
    for domain in domains:
        software_cache[domain] = await get_domain_software_info(domain)

    # 全ノートのプレビューカードをバッチ取得
    from app.models.preview_card import PreviewCard

    cards_result = await db.execute(select(PreviewCard).where(PreviewCard.note_id.in_(unique_ids)))
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
            pinned=bool(pinned_ids and n.id in pinned_ids),
        )
        result.append(resp)
    return result


@router.post(
    "",
    response_model=NoteResponse,
    status_code=201,
    dependencies=[Depends(require_oauth_scope("write:statuses"))],
)
async def create_status(
    body: NoteCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # in_reply_to_id の存在を検証
    visibility = "followers" if body.visibility == "private" else body.visibility
    if body.in_reply_to_id:
        parent = await get_note_by_id(db, body.in_reply_to_id)
        if not parent:
            raise HTTPException(status_code=404, detail="Reply target not found")
        # リプライの公開範囲は親ノートより広くできない
        vis_rank = {"public": 0, "unlisted": 1, "followers": 2, "direct": 3}
        parent_rank = vis_rank.get(parent.visibility, 0)
        reply_rank = vis_rank.get(visibility, 0)
        if reply_rank < parent_rank:
            visibility = parent.visibility

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
            visibility=visibility,
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


@router.put(
    "/{note_id}",
    response_model=NoteResponse,
    dependencies=[Depends(require_oauth_scope("write:statuses"))],
)
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

    # 現在の状態を編集履歴として保存
    from app.models.note_edit import NoteEdit

    edit_record = NoteEdit(
        note_id=note.id,
        content=note.content,
        source=note.source,
        spoiler_text=note.spoiler_text or "",
    )
    db.add(edit_record)

    # ノートを更新
    from app.utils.sanitize import text_to_html

    note.content = text_to_html(body.content)
    note.source = body.content
    note.spoiler_text = body.spoiler_text
    note.updated_at = datetime.now(timezone.utc)
    await db.commit()

    # フォロワーに AP Update を配送
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

    # レスポンス用にノートを再読み込み
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

    # 編集履歴を構築: 過去の編集 + 現在の状態
    history = [
        NoteEditHistoryEntry(
            content=e.content,
            source=e.source,
            spoiler_text=e.spoiler_text,
            created_at=e.created_at,
        )
        for e in edits
    ]
    # 現在のバージョンを追加
    history.append(
        NoteEditHistoryEntry(
            content=note.content,
            source=note.source,
            spoiler_text=note.spoiler_text or "",
            created_at=note.updated_at or note.published,
        )
    )
    return history


async def _batch_filter_visible(
    db: AsyncSession,
    notes: list,
    actor_id: uuid.UUID | None,
) -> list:
    """C-2: ノートリストの可視性をバッチチェックしてフィルタ。"""
    if not notes or actor_id is None:
        return [n for n in notes if n.visibility in ("public", "unlisted")]

    # followers可視性のノートのactor_idを収集し、フォロー状態を一括チェック
    followers_actor_ids = {
        n.actor_id for n in notes if n.visibility == "followers" and n.actor_id != actor_id
    }
    followed_ids: set = set()
    if followers_actor_ids:
        from app.models.follow import Follow

        follow_result = await db.execute(
            select(Follow.following_id).where(
                Follow.follower_id == actor_id,
                Follow.following_id.in_(followers_actor_ids),
                Follow.accepted.is_(True),
            )
        )
        followed_ids = {row[0] for row in follow_result.all()}

    visible = []
    for n in notes:
        if n.visibility in ("public", "unlisted"):
            visible.append(n)
        elif n.visibility == "followers":
            if n.actor_id == actor_id or n.actor_id in followed_ids:
                visible.append(n)
        elif n.visibility == "direct":
            if n.actor_id == actor_id:
                visible.append(n)
    return visible


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

    # C-1: 祖先ノードのIDを軽量クエリで収集してからバッチ取得
    MAX_ANCESTORS = 40
    MAX_DESCENDANTS = 200
    ancestor_ids: list[uuid.UUID] = []
    current_id = note.in_reply_to_id
    seen_ids: set[uuid.UUID] = {note.id}
    while current_id and current_id not in seen_ids and len(ancestor_ids) < MAX_ANCESTORS:
        seen_ids.add(current_id)
        ancestor_ids.append(current_id)
        row = await db.execute(
            select(Note.in_reply_to_id).where(Note.id == current_id, Note.deleted_at.is_(None))
        )
        current_id = row.scalar_one_or_none()
    ancestor_ids.reverse()

    ancestors = []
    if ancestor_ids:
        result = await db.execute(
            select(Note)
            .options(*_note_load_options())
            .where(Note.id.in_(ancestor_ids), Note.deleted_at.is_(None))
        )
        ancestor_map = {n.id: n for n in result.scalars().all()}
        ancestors = [ancestor_map[aid] for aid in ancestor_ids if aid in ancestor_map]
        # バッチ可視性チェック
        ancestors = await _batch_filter_visible(db, ancestors, actor_id)

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
            descendants.append(child)
            queue.append(child.id)

    # C-2: 子孫の可視性をバッチチェック
    descendants = await _batch_filter_visible(db, descendants, actor_id)

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


@router.post(
    "/{note_id}/react/{emoji}",
    dependencies=[Depends(require_oauth_scope("write:favourites"))],
)
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

    # ノート作成者に通知
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


@router.post(
    "/{note_id}/unreact/{emoji}",
    dependencies=[Depends(require_oauth_scope("write:favourites"))],
)
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


@router.put(
    "/{note_id}/emoji_reactions/{emoji}",
    response_model=NoteResponse,
    dependencies=[Depends(require_oauth_scope("write:favourites"))],
)
async def fedibird_react(
    note_id: uuid.UUID,
    emoji: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fedibird 互換: 絵文字リアクションを追加し、更新後のステータスを返す。"""
    from app.services.reaction_service import add_reaction

    note = await get_note_by_id(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    if not await check_note_visible(db, note, user.actor_id):
        raise HTTPException(status_code=404, detail="Note not found")

    try:
        await add_reaction(db, user, note, emoji)
    except ValueError:
        pass  # リアクション済み — 現在のステータスを返す

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


@router.delete(
    "/{note_id}/emoji_reactions/{emoji}",
    response_model=NoteResponse,
    dependencies=[Depends(require_oauth_scope("write:favourites"))],
)
async def fedibird_unreact(
    note_id: uuid.UUID,
    emoji: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fedibird 互換: 絵文字リアクションを削除し、更新後のステータスを返す。"""
    from app.services.reaction_service import remove_reaction

    note = await get_note_by_id(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    if not await check_note_visible(db, note, user.actor_id):
        raise HTTPException(status_code=404, detail="Note not found")

    try:
        await remove_reaction(db, user, note, emoji)
    except ValueError:
        pass  # 未リアクション — 現在のステータスを返す

    note = await get_note_by_id(db, note_id)
    reactions_map = await get_reaction_summaries(
        db, [note.id], user.actor_id, include_account_ids=True
    )
    return await note_to_response(
        note, reactions_map.get(note.id, []), db=db, actor_id=user.actor_id
    )


@router.post(
    "/{note_id}/favourite",
    response_model=NoteResponse,
    dependencies=[Depends(require_oauth_scope("write:favourites"))],
)
async def favourite_status(
    note_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """ステータスをお気に入りにする（⭐ リアクションのエイリアス）。"""
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


@router.post(
    "/{note_id}/unfavourite",
    response_model=NoteResponse,
    dependencies=[Depends(require_oauth_scope("write:favourites"))],
)
async def unfavourite_status(
    note_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """ステータスのお気に入りを解除する（⭐ リアクションの削除）。"""
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
    """ステータスをお気に入り（⭐ リアクション）したアカウント一覧を取得する。"""
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


@router.get("/{note_id}/reblogged_by")
async def reblogged_by(
    note_id: uuid.UUID,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """ステータスをリブログ（リノート）したアカウント一覧を取得する。"""
    from app.api.mastodon.accounts import _actor_to_account

    note = await get_note_by_id(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    actor_id = user.actor_id if user else None
    if not await check_note_visible(db, note, actor_id):
        raise HTTPException(status_code=404, detail="Note not found")

    result = await db.execute(
        select(Note)
        .options(selectinload(Note.actor))
        .where(
            Note.renote_of_id == note.id,
            Note.content == "",
            Note.deleted_at.is_(None),
        )
        .order_by(Note.published.desc())
        .limit(80)
    )
    renotes = result.scalars().all()

    return [await _actor_to_account(r.actor, db=db) for r in renotes]


@router.get("/{note_id}/reacted_by")
async def reacted_by(
    note_id: uuid.UUID,
    emoji: str | None = None,
    limit: int = Query(40, le=80),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    from app.api.mastodon.accounts import _actor_to_account
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
    query = query.limit(limit)

    result = await db.execute(query)
    reactions = result.scalars().all()

    results = []
    for r in reactions:
        account = await _actor_to_account(r.actor, db=db)
        account["domain"] = r.actor.domain
        account["is_cat"] = getattr(r.actor, "is_cat", False)
        results.append({"actor": account, "emoji": r.emoji})
    return results


@router.post(
    "/{note_id}/reblog",
    response_model=NoteResponse,
    status_code=200,
    dependencies=[Depends(require_oauth_scope("write:statuses"))],
)
async def reblog_status(
    note_id: uuid.UUID,
    visibility: str | None = Body(None, embed=True),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    original = await get_note_by_id(db, note_id)
    if not original:
        raise HTTPException(status_code=404, detail="Note not found")

    actor = user.actor

    if not await check_note_visible(db, original, actor.id):
        raise HTTPException(status_code=404, detail="Note not found")

    # direct でのブーストは常に不可
    if original.visibility == "direct":
        raise HTTPException(status_code=422, detail="Cannot reblog a direct post")

    # 他人の followers ノートはブースト不可（自分のノートは許可）
    if original.visibility == "followers" and original.actor_id != actor.id:
        raise HTTPException(status_code=422, detail="Cannot reblog a private post")

    # visibility が未指定の場合は元ノートの公開範囲を使用
    _RANK = {"public": 0, "unlisted": 1, "followers": 2, "direct": 3}
    reblog_vis = visibility or original.visibility
    # Mastodon API 互換: "private" → "followers"
    if reblog_vis == "private":
        reblog_vis = "followers"

    if reblog_vis not in ("public", "unlisted", "followers"):
        raise HTTPException(status_code=422, detail="Cannot reblog with direct visibility")

    # 元ノートの公開範囲より広い範囲でのブーストは不可
    if _RANK.get(reblog_vis, 3) < _RANK.get(original.visibility, 0):
        raise HTTPException(
            status_code=422,
            detail="Cannot reblog with wider visibility than the original",
        )

    # 既存のリブログを確認
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

    # 公開範囲に応じて to/cc を構築
    public = "https://www.w3.org/ns/activitystreams#Public"
    followers_url = actor.followers_url or ""
    if reblog_vis == "public":
        to_list = [public]
        cc_list = [followers_url]
    elif reblog_vis == "unlisted":
        to_list = [followers_url]
        cc_list = [public]
    else:  # followers
        to_list = [followers_url]
        cc_list = []

    reblog_note = Note(
        id=reblog_id,
        ap_id=ap_id,
        actor_id=actor.id,
        content="",
        visibility=reblog_vis,
        renote_of_id=original.id,
        renote_of_ap_id=original.ap_id,
        to=to_list,
        cc=cc_list,
        local=True,
    )
    db.add(reblog_note)
    original.renotes_count = original.renotes_count + 1
    await db.commit()

    # 元ノートの画像にフォーカルポイント検出・vision タグ付けを実行
    try:
        from sqlalchemy import select as _sel

        from app.models.note_attachment import NoteAttachment as _NA

        _IMAGE_MIMES = [
            "image/jpeg", "image/png", "image/webp",
            "image/gif", "image/avif", "image/apng",
        ]

        if settings.face_detect_enabled:
            _att_rows = await db.execute(
                _sel(_NA.id).where(
                    _NA.note_id == original.id,
                    _NA.remote_url.isnot(None),
                    _NA.remote_focal_x.is_(None),
                    _NA.remote_mime_type.in_(_IMAGE_MIMES),
                )
            )
            _att_ids = [row[0] for row in _att_rows.all()]
            if _att_ids:
                from app.services.face_detect_queue import enqueue_remote as _enqueue_fd

                await _enqueue_fd(original.id, _att_ids)

        if settings.neko_vision_enabled:
            _att_rows_v = await db.execute(
                _sel(_NA.id).where(
                    _NA.note_id == original.id,
                    _NA.remote_url.isnot(None),
                    _NA.vision_at.is_(None),
                    _NA.remote_mime_type.in_(_IMAGE_MIMES),
                )
            )
            _att_ids_v = [row[0] for row in _att_rows_v.all()]
            if _att_ids_v:
                from app.services.vision_queue import enqueue_remote as _enqueue_vis

                await _enqueue_vis(original.id, _att_ids_v, note_text=original.content)
    except Exception:
        pass  # 画像処理の失敗でブーストを失敗させない

    # 元ノートの作成者に通知
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

    # フォロワーに Announce を配送
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

    # ストリーミングイベントを発行し、フォロワーがリブログをリアルタイムで確認できるようにする
    try:
        import json as _json

        from app.services.follow_service import get_follower_ids
        from app.valkey_client import valkey as valkey_client

        event = _json.dumps({"event": "update", "payload": {"id": str(reblog_note.id)}})
        if reblog_vis == "public":
            await valkey_client.publish("timeline:public", event)
        follower_ids = await get_follower_ids(db, actor.id)
        for fid in follower_ids:
            await valkey_client.publish(f"timeline:home:{fid}", event)
        await valkey_client.publish(f"timeline:home:{actor.id}", event)
    except Exception:
        pass  # pub/sub の失敗でリブログを失敗させない

    # 配送コミット後にセッションが期限切れになるため再リフレッシュ
    await db.refresh(reblog_note, ["actor", "attachments"])
    await db.refresh(original, ["actor", "attachments"])
    return await note_to_response(reblog_note, reblog_note=original, db=db)


@router.post(
    "/{note_id}/unreblog",
    status_code=200,
    dependencies=[Depends(require_oauth_scope("write:statuses"))],
)
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

    # フォロワーに Undo(Announce) を配送
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


@router.post(
    "/{note_id}/bookmark",
    dependencies=[Depends(require_oauth_scope("write:bookmarks"))],
)
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


@router.post(
    "/{note_id}/unbookmark",
    dependencies=[Depends(require_oauth_scope("write:bookmarks"))],
)
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


@router.post(
    "/{note_id}/pin",
    dependencies=[Depends(require_oauth_scope("write:statuses"))],
)
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

    # フォロワーに Add アクティビティを配送
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


@router.post(
    "/{note_id}/unpin",
    dependencies=[Depends(require_oauth_scope("write:statuses"))],
)
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

    # フォロワーに Remove アクティビティを配送
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


@router.delete(
    "/{note_id}",
    status_code=204,
    dependencies=[Depends(require_oauth_scope("write:statuses"))],
)
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

    # 検索インデックスから削除
    from app.config import settings as _settings

    if _settings.neko_search_enabled:
        from app.services.search_queue import enqueue_delete

        await enqueue_delete(note.id)

    # フォロワーに Delete(Tombstone) を配送
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
