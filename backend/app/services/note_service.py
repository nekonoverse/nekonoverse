import math
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.activitypub import extract_mfm_source
from app.config import settings
from app.models.actor import Actor
from app.models.note import Note
from app.models.reaction import Reaction
from app.models.user import User
from app.utils.sanitize import MENTION_PATTERN, text_to_html

_EMOJI_SHORTCODE_RE = re.compile(r":([a-zA-Z0-9_]+):")
_CUSTOM_EMOJI_REACTION_RE = re.compile(r"^:([a-zA-Z0-9_]+)(?:@([a-zA-Z0-9.-]+))?:$")
_ISO_DURATION_RE = re.compile(
    r"^PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>[\d.]+)S)?$"
)


def _parse_iso_duration(s: str) -> float | None:
    """ISO 8601 duration 文字列 (PT...S) を秒数に変換する。"""
    m = _ISO_DURATION_RE.match(s)
    if not m:
        return None
    try:
        hours = float(m.group("hours") or 0)
        minutes = float(m.group("minutes") or 0)
        seconds = float(m.group("seconds") or 0)
    except ValueError:
        return None
    total = hours * 3600 + minutes * 60 + seconds
    return total if math.isfinite(total) else None


def extract_mentions(text: str) -> list[tuple[str, str | None]]:
    """テキストから (username, domain) タプルを抽出する。ローカルの場合domainはNone。"""
    return [(m.group(1), m.group(2)) for m in MENTION_PATTERN.finditer(text)]


async def create_note(
    db: AsyncSession,
    user: User,
    content: str,
    visibility: str = "public",
    sensitive: bool = False,
    spoiler_text: str | None = None,
    in_reply_to_id: uuid.UUID | None = None,
    media_ids: list[uuid.UUID] | None = None,
    quote_id: uuid.UUID | None = None,
    poll_options: list[str] | None = None,
    poll_expires_in: int | None = None,
    poll_multiple: bool = False,
) -> Note:
    # CW付きノートは自動的にsensitiveにする (Mastodon互換)
    if spoiler_text and not sensitive:
        sensitive = True

    actor = user.actor
    note_id = uuid.uuid4()
    ap_id = f"{settings.server_url}/notes/{note_id}"

    # 可視性に基づいてto/ccを構築
    public = "https://www.w3.org/ns/activitystreams#Public"
    to_list: list[str] = []
    cc_list: list[str] = []

    if visibility == "public":
        to_list = [public]
        cc_list = [actor.followers_url or ""]
    elif visibility == "unlisted":
        to_list = [actor.followers_url or ""]
        cc_list = [public]
    elif visibility == "followers":
        to_list = [actor.followers_url or ""]
    # direct: to/ccはメンション先アクターのみ (後で処理)

    # メンションを抽出してcc/toに追加
    mentions = extract_mentions(content)
    mention_data = []
    for username, domain in mentions:
        from app.services.actor_service import actor_uri, get_actor_by_username

        mentioned_actor = await get_actor_by_username(db, username, domain)
        # リモートユーザーがDBに未登録の場合、WebFingerで解決
        if not mentioned_actor and domain:
            from app.services.actor_service import resolve_webfinger

            try:
                mentioned_actor = await resolve_webfinger(db, username, domain)
            except Exception:
                await db.rollback()
                mentioned_actor = None  # WebFinger解決失敗はスキップ
        if mentioned_actor:
            mentioned_uri = actor_uri(mentioned_actor)
            mention_data.append(
                {
                    "ap_id": mentioned_uri,
                    "username": mentioned_actor.username,
                    "domain": mentioned_actor.domain,
                }
            )
            if visibility == "direct":
                if mentioned_uri not in to_list:
                    to_list.append(mentioned_uri)
            else:
                if mentioned_uri not in cc_list:
                    cc_list.append(mentioned_uri)

    # リプライ先の解決: AP ID取得 + 作者をcc/toに追加 (AP配送に必要)
    in_reply_to_ap_id = None
    if in_reply_to_id:
        parent = await get_note_by_id(db, in_reply_to_id)
        if parent:
            in_reply_to_ap_id = parent.ap_id
            if parent.actor:
                from app.services.actor_service import actor_uri

                parent_uri = actor_uri(parent.actor)
                if visibility == "direct":
                    if parent_uri not in to_list:
                        to_list.append(parent_uri)
                else:
                    if parent_uri not in cc_list:
                        cc_list.append(parent_uri)

    html_content = text_to_html(content)

    # 引用ノートの解決
    quote_ap_id = None
    if quote_id:
        quoted = await get_note_by_id(db, quote_id)
        if quoted:
            quote_ap_id = quoted.ap_id
        else:
            quote_id = None

    note = Note(
        id=note_id,
        ap_id=ap_id,
        actor_id=actor.id,
        content=html_content,
        source=content,
        visibility=visibility,
        sensitive=sensitive,
        spoiler_text=spoiler_text,
        to=to_list,
        cc=cc_list,
        local=True,
        in_reply_to_id=in_reply_to_id,
        in_reply_to_ap_id=in_reply_to_ap_id,
        mentions=mention_data,
        quote_id=quote_id,
        quote_ap_id=quote_ap_id,
    )

    # 投票サポート
    if poll_options:
        from datetime import datetime, timedelta, timezone

        note.is_poll = True
        note.poll_options = [{"title": opt, "votes_count": 0} for opt in poll_options]
        note.poll_multiple = poll_multiple
        if poll_expires_in:
            note.poll_expires_at = datetime.now(timezone.utc) + timedelta(seconds=poll_expires_in)
    db.add(note)

    # 親ノートの返信数をインクリメント
    if in_reply_to_id:
        parent = await get_note_by_id(db, in_reply_to_id)
        if parent:
            parent.replies_count = parent.replies_count + 1

    # メディアファイルを添付
    if media_ids:
        from app.models.note_attachment import NoteAttachment
        from app.services.drive_service import get_drive_file

        for position, file_id in enumerate(media_ids[:4]):
            drive_file = await get_drive_file(db, file_id)
            if drive_file and drive_file.owner_id == user.id:
                attachment = NoteAttachment(
                    note_id=note_id,
                    drive_file_id=drive_file.id,
                    position=position,
                )
                db.add(attachment)

    await db.commit()

    # レンダリングとレスポンス用に全リレーションを含めてノートを再読み込み
    note = await get_note_by_id(db, note_id)

    # ハッシュタグの抽出とupsert
    from app.services.hashtag_service import extract_hashtags
    from app.services.hashtag_service import upsert_hashtags as upsert_ht

    hashtag_names = extract_hashtags(content)
    if hashtag_names:
        await upsert_ht(db, note_id, hashtag_names)
        note._hashtag_names = hashtag_names

    # AP連合タグ用にカスタム絵文字ショートコードを抽出
    shortcodes = set(_EMOJI_SHORTCODE_RE.findall(content))
    if shortcodes:
        from app.services.emoji_service import get_custom_emoji

        emoji_tags = []
        for sc in shortcodes:
            emoji = await get_custom_emoji(db, sc, None)
            if emoji and not emoji.local_only:
                emoji_tags.append(
                    {
                        "shortcode": emoji.shortcode,
                        "url": emoji.url,
                        "aliases": emoji.aliases,
                        "license": emoji.license,
                        "is_sensitive": emoji.is_sensitive,
                        "author": emoji.author,
                        "description": emoji.description,
                        "copy_permission": emoji.copy_permission,
                        "usage_info": emoji.usage_info,
                        "is_based_on": emoji.is_based_on,
                        "category": emoji.category,
                    }
                )
        if emoji_tags:
            note._emoji_tags = emoji_tags

    # フォロワーとメンション先のリモートユーザーに配送
    if visibility in ("public", "unlisted", "followers", "direct"):
        from app.activitypub.renderer import render_create_activity
        from app.services.delivery_service import enqueue_delivery
        from app.services.follow_service import get_follower_inboxes

        activity = render_create_activity(note)
        inboxes: set[str] = set()

        # フォロワーへの配送 (direct以外)
        if visibility != "direct":
            follower_inboxes = await get_follower_inboxes(db, actor.id)
            inboxes.update(follower_inboxes)

        # メンション先リモートユーザーへの配送
        for m in mention_data:
            if m.get("domain"):
                from app.services.actor_service import get_actor_by_username

                mentioned = await get_actor_by_username(db, m["username"], m["domain"])
                if mentioned and mentioned.inbox_url:
                    inbox = mentioned.shared_inbox_url or mentioned.inbox_url
                    inboxes.add(inbox)

        # リプライ先のリモートユーザーへの配送
        if in_reply_to_id:
            parent = await get_note_by_id(db, in_reply_to_id)
            if parent and parent.actor and parent.actor.domain:
                inbox = parent.actor.shared_inbox_url or parent.actor.inbox_url
                if inbox:
                    inboxes.add(inbox)

        for inbox_url in inboxes:
            await enqueue_delivery(db, actor.id, inbox_url, activity)

    # 通知を送信
    from app.services.notification_service import create_notification, publish_notification

    pending_notifs = []

    # リプライ先アクターを特定し、メンション+リプライの重複通知を防止
    reply_recipient_id = None
    if in_reply_to_id:
        parent = await get_note_by_id(db, in_reply_to_id)
        if parent and parent.actor.is_local:
            reply_recipient_id = parent.actor_id
            notif = await create_notification(
                db,
                "reply",
                parent.actor_id,
                actor.id,
                note_id,
            )
            if notif:
                pending_notifs.append(notif)

    # メンション通知 (ローカルアクターのみ、リプライ先はスキップ)
    for m in mention_data:
        if not m.get("domain"):  # local actor
            from app.services.actor_service import get_actor_by_username

            mentioned = await get_actor_by_username(db, m["username"], None)
            if mentioned and mentioned.id != reply_recipient_id:
                notif = await create_notification(
                    db,
                    "mention",
                    mentioned.id,
                    actor.id,
                    note_id,
                )
                if notif:
                    pending_notifs.append(notif)

    await db.commit()

    # コミット後に通知イベントをパブリッシュ
    for notif in pending_notifs:
        await publish_notification(notif)

    # Valkey pub/sub経由でリアルタイムイベントをパブリッシュ
    try:
        import json

        from app.services.follow_service import get_follower_ids
        from app.valkey_client import valkey as valkey_client

        event = json.dumps({"event": "update", "payload": {"id": str(note_id)}})
        if visibility == "public":
            await valkey_client.publish("timeline:public", event)
        follower_ids = await get_follower_ids(db, actor.id)

        # Exclusive リスト除外: このアクターを exclusive リストに入れているユーザーの
        # ホームTLには配信しない
        from app.services.list_service import (
            get_exclusive_list_user_actor_ids,
            get_list_ids_for_actor,
        )

        exclusive_user_ids = await get_exclusive_list_user_actor_ids(db, actor.id)

        # M-9: Valkeyパイプラインで一括pub/sub
        pipe = valkey_client.pipeline()
        for fid in follower_ids:
            if fid not in exclusive_user_ids:
                pipe.publish(f"timeline:home:{fid}", event)
        if actor.id not in exclusive_user_ids:
            pipe.publish(f"timeline:home:{actor.id}", event)

        # リストタイムラインチャンネルに配信
        list_ids = await get_list_ids_for_actor(db, actor.id)
        for lid in list_ids:
            pipe.publish(f"timeline:list:{lid}", event)

        await pipe.execute()
    except Exception:
        pass  # pub/sub失敗でノート作成を失敗させない

    # URL要約抽出をエンキュー (summary proxyが設定されている場合)
    if content:
        from app.services.summary_proxy_queue import enqueue as enqueue_summary

        first_url = _extract_first_url(content)
        if first_url:
            await enqueue_summary(note_id, first_url)

    # 検索インデックスをエンキュー (neko-searchが設定されている場合)
    if settings.neko_search_enabled and visibility == "public":
        from app.services.search_queue import enqueue_index

        await enqueue_index(note_id, content, note.published)

    # 画像タグ付けをエンキュー (neko-visionが設定されている場合)
    if settings.neko_vision_enabled and media_ids:
        from app.services.vision_queue import enqueue_local as enqueue_vision
        from app.services.vision_service import collect_reply_context

        reply_ctx = await collect_reply_context(db, note)
        for file_id in media_ids:
            await enqueue_vision(file_id, note_id, note_text=content, context=reply_ctx)

    # M-12: statuses_countキャッシュを無効化
    try:
        await valkey_client.delete(f"perf:statuses_count:{actor.id}")
    except Exception:
        pass

    # 配送コミット後に最新の状態を取得するため再クエリ
    return await get_note_by_id(db, note_id)


_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")


def _extract_first_url(text: str) -> str | None:
    """プレーンテキストから最初のHTTP(S) URLを抽出する。"""
    m = _URL_RE.search(text)
    if m:
        url = m.group(0)
        # 末尾の句読点を除去
        url = url.rstrip(".,;:!?")
        return url
    return None


def _note_load_options():
    """Noteクエリ用の標準eager-loadingオプション。"""
    return [
        selectinload(Note.actor),
        selectinload(Note.attachments),
        selectinload(Note.quoted_note).selectinload(Note.actor),
        selectinload(Note.quoted_note).selectinload(Note.attachments),
        # リノート(ブースト)元ノートとそのサブリレーション
        selectinload(Note.renote_of).selectinload(Note.actor),
        selectinload(Note.renote_of).selectinload(Note.attachments),
        selectinload(Note.renote_of).selectinload(Note.quoted_note).selectinload(Note.actor),
        selectinload(Note.renote_of).selectinload(Note.quoted_note).selectinload(Note.attachments),
        # リプライ先ノートのアクター（in_reply_to_account_id解決用）
        selectinload(Note.in_reply_to).selectinload(Note.actor),
    ]


async def get_note_by_id(db: AsyncSession, note_id: uuid.UUID) -> Note | None:
    result = await db.execute(
        select(Note)
        .options(*_note_load_options())
        .where(Note.id == note_id, Note.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def check_note_visible(
    db: AsyncSession,
    note: Note,
    current_actor_id: uuid.UUID | None = None,
) -> bool:
    """現在のユーザーがこのノートを閲覧可能かどうかを確認する。"""
    # 作者は自分のノートを常に閲覧可能
    if current_actor_id and note.actor_id == current_actor_id:
        return True

    actor = note.actor

    # Misskey: make_notes_hidden_before — このタイムスタンプより前のノートを全員から非表示
    if getattr(actor, "make_notes_hidden_before", None) and note.published:
        threshold = datetime.fromtimestamp(actor.make_notes_hidden_before / 1000.0, tz=timezone.utc)
        if note.published < threshold:
            return False

    # Misskey: make_notes_followers_only_before — 古いノートをフォロワー限定として扱う
    if getattr(actor, "make_notes_followers_only_before", None) and note.published:
        threshold = datetime.fromtimestamp(
            actor.make_notes_followers_only_before / 1000.0,
            tz=timezone.utc,
        )
        if note.published < threshold:
            if not current_actor_id:
                return False
            from app.models.follow import Follow as FollowModel

            result = await db.execute(
                select(FollowModel.id)
                .where(
                    FollowModel.following_id == note.actor_id,
                    FollowModel.follower_id == current_actor_id,
                    FollowModel.accepted.is_(True),
                )
                .limit(1)
            )
            if result.scalar_one_or_none() is None:
                return False

    if note.visibility in ("public", "unlisted"):
        return True
    if not current_actor_id:
        return False
    if note.visibility == "followers":
        from app.models.follow import Follow

        result = await db.execute(
            select(Follow.id)
            .where(
                Follow.following_id == note.actor_id,
                Follow.follower_id == current_actor_id,
                Follow.accepted.is_(True),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None
    if note.visibility == "direct":
        from app.models.actor import Actor

        result = await db.execute(select(Actor.ap_id).where(Actor.id == current_actor_id))
        actor_ap_id = result.scalar_one_or_none()
        if not actor_ap_id:
            return False
        return any(m.get("ap_id") == actor_ap_id for m in (note.mentions or []))
    return False


async def get_note_by_ap_id(db: AsyncSession, ap_id: str) -> Note | None:
    result = await db.execute(
        select(Note)
        .options(*_note_load_options())
        .where(Note.ap_id == ap_id, Note.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def _get_excluded_ids(db: AsyncSession, actor_id: uuid.UUID) -> list[uuid.UUID]:
    """指定アクターがブロックまたはミュートしているアクターのIDを取得する。"""
    from app.services.block_service import get_blocked_ids
    from app.services.mute_service import get_muted_ids

    blocked = await get_blocked_ids(db, actor_id)
    muted = await get_muted_ids(db, actor_id)
    return list(set(blocked + muted))


async def get_public_timeline(
    db: AsyncSession,
    limit: int = 20,
    max_id: uuid.UUID | None = None,
    local_only: bool = False,
    current_actor_id: uuid.UUID | None = None,
) -> list[Note]:
    query = (
        select(Note)
        .join(Actor, Note.actor_id == Actor.id)
        .options(*_note_load_options())
        .where(
            Note.visibility == "public",
            Note.deleted_at.is_(None),
            Actor.silenced_at.is_(None),
        )
    )
    if local_only:
        query = query.where(Note.local.is_(True))
    if current_actor_id:
        excluded = await _get_excluded_ids(db, current_actor_id)
        if excluded:
            query = query.where(Note.actor_id.not_in(excluded))
    else:
        # 未認証: require_signin_to_viewが有効なアクターを除外
        query = query.where(Actor.require_signin_to_view.is_(False))

    # しきい値より前の非表示ノートを除外 (全ユーザー対象)
    query = query.where(
        or_(
            Actor.make_notes_hidden_before.is_(None),
            Note.published > func.to_timestamp(Actor.make_notes_hidden_before / 1000.0),
        )
    )

    # 未認証: フォロワー限定しきい値より前のノートも除外
    if not current_actor_id:
        query = query.where(
            or_(
                Actor.make_notes_followers_only_before.is_(None),
                Note.published > func.to_timestamp(Actor.make_notes_followers_only_before / 1000.0),
            )
        )

    if max_id:
        # カーソルページネーション用にmax_idノートの投稿日時を取得
        sub = select(Note.published).where(Note.id == max_id).scalar_subquery()
        query = query.where(Note.published < sub)
    query = query.order_by(Note.published.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


def _escape_like(value: str) -> str:
    """LIKE/ILIKE パターンの特殊文字をエスケープする。"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def get_media_timeline(
    db: AsyncSession,
    limit: int = 20,
    max_id: uuid.UUID | None = None,
    q: str | None = None,
    current_actor_id: uuid.UUID | None = None,
) -> list[Note]:
    """メディア添付を持つノートのタイムラインを取得する。

    画像/動画のあるノートを新しい順に返す。
    q が指定された場合、vision_tags / vision_caption / ノート本文で全文検索する。
    """
    from sqlalchemy import Text, exists

    from app.models.drive_file import DriveFile
    from app.models.note_attachment import NoteAttachment

    # メディア添付の EXISTS サブクエリ
    media_exists = (
        select(NoteAttachment.id)
        .outerjoin(DriveFile, NoteAttachment.drive_file_id == DriveFile.id)
        .where(
            NoteAttachment.note_id == Note.id,
            or_(
                DriveFile.mime_type.like("image/%"),
                DriveFile.mime_type.like("video/%"),
                NoteAttachment.remote_mime_type.like("image/%"),
                NoteAttachment.remote_mime_type.like("video/%"),
            ),
        )
        .correlate(Note)
    )

    query = (
        select(Note)
        .join(Actor, Note.actor_id == Actor.id)
        .options(*_note_load_options())
        .where(
            exists(media_exists),
            Note.visibility.in_(("public", "unlisted")),
            Note.deleted_at.is_(None),
            Note.renote_of_id.is_(None),
            Actor.silenced_at.is_(None),
        )
    )

    # 検索フィルタ: vision + ノート本文
    if q:
        pattern = f"%{_escape_like(q)}%"
        # vision フィールドに一致する添付の EXISTS
        vision_match = (
            select(NoteAttachment.id)
            .outerjoin(DriveFile, NoteAttachment.drive_file_id == DriveFile.id)
            .where(
                NoteAttachment.note_id == Note.id,
                or_(
                    DriveFile.vision_caption.ilike(pattern),
                    DriveFile.vision_tags.cast(Text).ilike(pattern),
                    NoteAttachment.remote_vision_caption.ilike(pattern),
                    NoteAttachment.remote_vision_tags.cast(Text).ilike(pattern),
                ),
            )
            .correlate(Note)
        )
        query = query.where(
            or_(
                exists(vision_match),
                Note.source.ilike(pattern),
                Note.content.ilike(pattern),
            )
        )

    # ブロック/ミュート除外
    if current_actor_id:
        excluded = await _get_excluded_ids(db, current_actor_id)
        if excluded:
            query = query.where(Note.actor_id.not_in(excluded))
    else:
        query = query.where(Actor.require_signin_to_view.is_(False))

    # しきい値より前の非表示ノートを除外
    query = query.where(
        or_(
            Actor.make_notes_hidden_before.is_(None),
            Note.published > func.to_timestamp(
                Actor.make_notes_hidden_before / 1000.0
            ),
        )
    )
    if not current_actor_id:
        query = query.where(
            or_(
                Actor.make_notes_followers_only_before.is_(None),
                Note.published > func.to_timestamp(
                    Actor.make_notes_followers_only_before / 1000.0
                ),
            )
        )

    # カーソルページネーション
    if max_id:
        sub = select(Note.published).where(Note.id == max_id).scalar_subquery()
        query = query.where(Note.published < sub)

    query = query.order_by(Note.published.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_home_timeline(
    db: AsyncSession,
    user: User,
    limit: int = 20,
    max_id: uuid.UUID | None = None,
) -> list[Note]:
    from app.models.follow import Follow

    actor_id = user.actor_id

    # このユーザーがフォローしているアクターのIDを取得
    following_result = await db.execute(
        select(Follow.following_id).where(
            Follow.follower_id == actor_id,
            Follow.accepted.is_(True),
        )
    )
    following_ids = [row[0] for row in following_result.all()]
    # 自分自身を含める
    following_ids.append(actor_id)

    # ブロック/ミュート済みアクターを除外
    excluded = await _get_excluded_ids(db, actor_id)
    visible_ids = [fid for fid in following_ids if fid not in excluded]

    # exclusiveリストに含まれるアクターを除外 (リストTLに表示されるため)
    from app.services.list_service import get_exclusive_list_actor_ids

    exclusive_ids = await get_exclusive_list_actor_ids(db, user.id)
    if exclusive_ids:
        visible_ids = [vid for vid in visible_ids if vid not in exclusive_ids]

    query = (
        select(Note)
        .options(*_note_load_options())
        .where(
            Note.actor_id.in_(visible_ids),
            Note.deleted_at.is_(None),
            Note.visibility.in_(["public", "unlisted", "followers"]),
        )
    )
    if max_id:
        sub = select(Note.published).where(Note.id == max_id).scalar_subquery()
        query = query.where(Note.published < sub)
    query = query.order_by(Note.published.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_reaction_summary(
    db: AsyncSession, note_id: uuid.UUID, current_actor_id: uuid.UUID | None = None
) -> list[dict]:
    """ノートの集計済みリアクションを取得する。"""
    result = await db.execute(
        select(Reaction.emoji, func.count(Reaction.id).label("count"))
        .where(Reaction.note_id == note_id)
        .group_by(Reaction.emoji)
        .order_by(func.count(Reaction.id).desc())
    )
    summaries = []
    for emoji, count in result.all():
        me = False
        if current_actor_id:
            me_result = await db.execute(
                select(Reaction.id).where(
                    Reaction.note_id == note_id,
                    Reaction.actor_id == current_actor_id,
                    Reaction.emoji == emoji,
                )
            )
            me = me_result.scalar_one_or_none() is not None

        # カスタム絵文字のURLを解決 (ローカル版を優先)
        emoji_url = None
        m = _CUSTOM_EMOJI_REACTION_RE.match(emoji)
        if m:
            from app.models.custom_emoji import CustomEmoji
            from app.services.emoji_service import get_custom_emoji

            shortcode, domain = m.group(1), m.group(2)
            local = await get_custom_emoji(db, shortcode, None)
            if local:
                emoji_url = local.url
            elif domain:
                remote = await get_custom_emoji(db, shortcode, domain)
                if remote:
                    emoji_url = remote.url
            else:
                # リアクション文字列にドメインなし (例: Misskeyは ":blobcat:" を
                # ドメインなしで送信) — このショートコードのリモート絵文字を検索
                result2 = await db.execute(
                    select(CustomEmoji)
                    .where(
                        CustomEmoji.shortcode == shortcode,
                        CustomEmoji.domain.isnot(None),
                    )
                    .limit(1)
                )
                remote = result2.scalar_one_or_none()
                if remote:
                    emoji_url = remote.url

        from app.utils.media_proxy import media_proxy_url

        is_importable = False
        import_domain: str | None = None
        if m and not local:
            # ローカルコピーのないカスタム絵文字 → インポート可能
            shortcode_val = m.group(1)
            domain_val = m.group(2)
            if domain_val:
                is_importable = True
                import_domain = domain_val
            elif emoji_url:
                # リアクション文字列にドメインなしだがリモート絵文字が見つかった
                remote_q = await db.execute(
                    select(CustomEmoji.domain)
                    .where(
                        CustomEmoji.shortcode == shortcode_val,
                        CustomEmoji.domain.isnot(None),
                    )
                    .limit(1)
                )
                remote_domain = remote_q.scalar_one_or_none()
                if remote_domain:
                    is_importable = True
                    import_domain = remote_domain

        entry: dict = {
            "emoji": emoji,
            "count": count,
            "me": me,
            "emoji_url": media_proxy_url(emoji_url, variant="emoji") if emoji_url else None,
            "importable": is_importable,
        }
        if is_importable:
            entry["import_domain"] = import_domain
        summaries.append(entry)
    return summaries


async def get_reaction_summaries(
    db: AsyncSession,
    note_ids: list[uuid.UUID],
    current_actor_id: uuid.UUID | None = None,
    include_account_ids: bool = False,
) -> dict[uuid.UUID, list[dict]]:
    """複数ノートの集計済みリアクションをバッチ取得する。

    note_id -> リアクションサマリーdictのリストを返す。
    全リアクションデータを一括取得することでN+1クエリを回避する。
    """
    from app.models.custom_emoji import CustomEmoji
    from app.utils.media_proxy import media_proxy_url

    if not note_ids:
        return {}

    # 1) (note_id, emoji) でグループ化した全リアクション数を1クエリで取得
    result = await db.execute(
        select(
            Reaction.note_id,
            Reaction.emoji,
            func.count(Reaction.id).label("count"),
        )
        .where(Reaction.note_id.in_(note_ids))
        .group_by(Reaction.note_id, Reaction.emoji)
        .order_by(Reaction.note_id, func.count(Reaction.id).desc())
    )
    rows = result.all()

    # 2) 「自分」のリアクションを1クエリで取得 (現在のユーザーがどの絵文字でリアクションしたか)
    me_set: set[tuple[uuid.UUID, str]] = set()
    if current_actor_id:
        me_result = await db.execute(
            select(Reaction.note_id, Reaction.emoji).where(
                Reaction.note_id.in_(note_ids),
                Reaction.actor_id == current_actor_id,
            )
        )
        for note_id_val, emoji_val in me_result.all():
            me_set.add((note_id_val, emoji_val))

    # 3) URL解決が必要な全カスタム絵文字ショートコードを収集
    custom_emojis_needed: dict[str, str | None] = {}  # shortcode -> domain
    for _, emoji_str, _ in rows:
        m = _CUSTOM_EMOJI_REACTION_RE.match(emoji_str)
        if m:
            shortcode, domain = m.group(1), m.group(2)
            # 常にローカルを先に試すため、ショートコードをdomainなしで追跡
            if shortcode not in custom_emojis_needed:
                custom_emojis_needed[shortcode] = domain

    # 4) 必要な全カスタム絵文字を最大2クエリでバッチ取得
    emoji_url_map: dict[str, str | None] = {}  # emoji string -> url
    importable_emojis: dict[str, str] = {}  # emoji_str -> remote domain
    if custom_emojis_needed:
        all_shortcodes = set(custom_emojis_needed.keys())

        # ローカル絵文字を取得
        local_result = await db.execute(
            select(CustomEmoji).where(
                CustomEmoji.shortcode.in_(all_shortcodes),
                CustomEmoji.domain.is_(None),
            )
        )
        local_emojis = {e.shortcode: e for e in local_result.scalars().all()}

        # リモート検索が必要なショートコードを収集
        remote_shortcodes = all_shortcodes - set(local_emojis.keys())
        remote_emojis: dict[str, CustomEmoji] = {}
        if remote_shortcodes:
            remote_result = await db.execute(
                select(CustomEmoji).where(
                    CustomEmoji.shortcode.in_(remote_shortcodes),
                    CustomEmoji.domain.isnot(None),
                )
            )
            for e in remote_result.scalars().all():
                # ショートコードごとに最初の一致を保持 (指定があればドメインも一致)
                if e.shortcode not in remote_emojis:
                    remote_emojis[e.shortcode] = e

        # 絵文字文字列 -> URLのマップを構築
        for _, emoji_str, _ in rows:
            m = _CUSTOM_EMOJI_REACTION_RE.match(emoji_str)
            if m:
                shortcode, domain = m.group(1), m.group(2)
                if shortcode in local_emojis:
                    emoji_url_map[emoji_str] = local_emojis[shortcode].url
                elif shortcode in remote_emojis:
                    emoji_url_map[emoji_str] = remote_emojis[shortcode].url
                    importable_emojis[emoji_str] = remote_emojis[shortcode].domain

    # 5) Fedibird互換用に (note_id, emoji) ごとのaccount_idsをオプションで取得
    account_ids_map: dict[tuple[uuid.UUID, str], list[str]] = {}
    if include_account_ids:
        from app.models.actor import Actor

        aid_result = await db.execute(
            select(Reaction.note_id, Reaction.emoji, Actor.id)
            .join(Actor, Reaction.actor_id == Actor.id)
            .where(Reaction.note_id.in_(note_ids))
        )
        for nid, emoji_str, actor_id_val in aid_result.all():
            key = (nid, emoji_str)
            account_ids_map.setdefault(key, []).append(str(actor_id_val))

    # 6) 結果dictを構築
    summaries: dict[uuid.UUID, list[dict]] = {nid: [] for nid in note_ids}
    for note_id_val, emoji_str, count in rows:
        me = (note_id_val, emoji_str) in me_set
        emoji_url = emoji_url_map.get(emoji_str)
        is_importable = emoji_str in importable_emojis
        entry: dict = {
            "emoji": emoji_str,
            "count": count,
            "me": me,
            "emoji_url": media_proxy_url(emoji_url, variant="emoji") if emoji_url else None,
            "importable": is_importable,
        }
        if is_importable:
            entry["import_domain"] = importable_emojis[emoji_str]
        if include_account_ids:
            entry["account_ids"] = account_ids_map.get(
                (note_id_val, emoji_str), []
            )
        summaries[note_id_val].append(entry)
    return summaries


async def get_statuses_count(db: AsyncSession, actor_id: uuid.UUID) -> int:
    """指定アクターのpublic/unlistedステータス数を返す。

    Valkeyに5分間キャッシュされる。
    """
    import json

    from app.valkey_client import valkey

    cache_key = f"perf:statuses_count:{actor_id}"
    try:
        cached = await valkey.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    result = await db.execute(
        select(func.count())
        .select_from(Note)
        .where(
            Note.actor_id == actor_id,
            Note.visibility.in_(["public", "unlisted"]),
            Note.deleted_at.is_(None),
        )
    )
    count = result.scalar() or 0

    try:
        await valkey.set(cache_key, json.dumps(count), ex=300)
    except Exception:
        pass

    return count


_FETCH_MAX_DEPTH = 3


async def fetch_remote_note(
    db: AsyncSession,
    ap_id: str,
    *,
    _depth: int = 0,
) -> Note | None:
    """AP IDでリモートノートを取得しローカルに保存する。

    参照先ノート (ブースト対象や引用対象) がローカルDBにない場合に
    announce/createハンドラから使用される。
    """
    import logging

    if _depth >= _FETCH_MAX_DEPTH:
        logging.getLogger(__name__).warning(
            "fetch_remote_note depth limit reached for %s",
            ap_id,
        )
        return None

    from app.models.note_attachment import NoteAttachment
    from app.services.actor_service import fetch_remote_actor, get_actor_by_ap_id
    from app.utils.sanitize import sanitize_html

    logger = logging.getLogger(__name__)

    # DBに既にあればそれを返す
    existing = await get_note_by_ap_id(db, ap_id)
    if existing:
        # 既存ノートでもfocal未検出の画像があればエンキュー
        if settings.face_detect_enabled:
            from sqlalchemy import select as sel

            from app.models.note_attachment import NoteAttachment as NA

            att_rows = await db.execute(
                sel(NA.id).where(
                    NA.note_id == existing.id,
                    NA.remote_url.isnot(None),
                    NA.remote_focal_x.is_(None),
                    NA.remote_mime_type.in_(
                        ["image/jpeg", "image/png", "image/webp", "image/gif", "image/avif", "image/apng"]
                    ),
                )
            )
            att_ids = [row[0] for row in att_rows.all()]
            if att_ids:
                from app.services.face_detect_queue import enqueue_remote

                await enqueue_remote(existing.id, att_ids)

        # 画像タグ付け (neko-vision)
        if settings.neko_vision_enabled:
            from app.models.note_attachment import NoteAttachment as NAV

            att_rows_v = await db.execute(
                select(NAV.id).where(
                    NAV.note_id == existing.id,
                    NAV.remote_url.isnot(None),
                    NAV.vision_at.is_(None),
                    NAV.remote_mime_type.in_(
                        ["image/jpeg", "image/png", "image/webp", "image/gif",
                         "image/avif", "image/apng"]
                    ),
                )
            )
            att_ids_v = [row[0] for row in att_rows_v.all()]
            if att_ids_v:
                from app.services.vision_queue import enqueue_remote as enqueue_vision_remote

                await enqueue_vision_remote(
                    existing.id, att_ids_v, note_text=existing.content
                )
        return existing

    try:
        from app.services.actor_service import _signed_get

        resp = await _signed_get(db, ap_id)
        if not resp or resp.status_code != 200:
            status = getattr(resp, "status_code", "no response")
            logger.warning("Failed to fetch remote note %s: %s", ap_id, status)
            return None
        data = resp.json()
    except Exception:
        logger.exception("Error fetching remote note %s", ap_id)
        return None

    obj_type = data.get("type")
    if obj_type not in ("Note", "Question"):
        logger.info("Fetched object %s is type %s, not Note", ap_id, obj_type)
        return None

    note_ap_id = data.get("id")
    if not note_ap_id:
        return None

    # M-12: リクエストURLとレスポンスidのドメイン一致検証
    from urllib.parse import urlparse as _urlparse

    req_domain = _urlparse(ap_id).hostname
    res_domain = _urlparse(note_ap_id).hostname
    if req_domain and res_domain and req_domain != res_domain:
        logger.warning("Domain mismatch for note: requested %s but got id %s", ap_id, note_ap_id)
        return None

    # 重複チェック(fetchの間に別のリクエストで作成された可能性)
    existing = await get_note_by_ap_id(db, note_ap_id)
    if existing:
        return existing

    actor_ap_id = data.get("attributedTo")
    if not actor_ap_id:
        return None

    actor = await get_actor_by_ap_id(db, actor_ap_id)
    if not actor:
        actor = await fetch_remote_actor(db, actor_ap_id)
    if not actor:
        logger.warning("Could not resolve actor %s for fetched note %s", actor_ap_id, note_ap_id)
        return None

    raw_content = data.get("content", "")
    # contentMap (多言語) フォールバック: デフォルト言語または最初の値を優先
    if not isinstance(raw_content, str):
        content_map = data.get("contentMap", {})
        if isinstance(content_map, dict) and content_map:
            raw_content = next(iter(content_map.values()))
        if not isinstance(raw_content, str):
            raw_content = ""
    content = sanitize_html(raw_content)
    source = extract_mfm_source(data)

    # 可視性判定
    to_list = data.get("to", [])
    cc_list = data.get("cc", [])
    public = "https://www.w3.org/ns/activitystreams#Public"
    if public in to_list:
        visibility = "public"
    elif public in cc_list:
        visibility = "unlisted"
    elif any(url.endswith("/followers") for url in to_list):
        visibility = "followers"
    else:
        visibility = "direct"

    # リプライ解決
    in_reply_to_ap_id = data.get("inReplyTo")
    in_reply_to_id = None
    if in_reply_to_ap_id:
        reply_note = await get_note_by_ap_id(db, in_reply_to_ap_id)
        if reply_note:
            in_reply_to_id = reply_note.id

    # 引用解決 (再帰fetchはしない)
    quote_ap_id = data.get("_misskey_quote") or data.get("quoteUrl") or data.get("quoteUri")
    quote_id = None
    if quote_ap_id:
        quoted_note = await get_note_by_ap_id(db, quote_ap_id)
        if quoted_note:
            quote_id = quoted_note.id

    # メンションとカスタム絵文字
    tags = data.get("tag", [])
    if isinstance(tags, dict):
        tags = [tags]
    mentions_list = []
    for tag in tags:
        if isinstance(tag, dict) and tag.get("type") == "Mention":
            href = tag.get("href", "")
            name = tag.get("name", "")
            mentions_list.append({"ap_id": href, "name": name})
        elif isinstance(tag, dict) and tag.get("type") == "Emoji":
            icon = tag.get("icon", {})
            emoji_url = icon.get("url") if isinstance(icon, dict) else None
            emoji_name = tag.get("name", "").strip(":")
            if emoji_name and emoji_url and actor.domain:
                from app.services.emoji_service import upsert_remote_emoji

                static_url = icon.get("staticUrl") if isinstance(icon, dict) else None
                _ml = tag.get("_misskey_license")
                license_text = tag.get("license") or (
                    _ml.get("freeText") if isinstance(_ml, dict) else None
                )
                await upsert_remote_emoji(
                    db,
                    shortcode=emoji_name,
                    domain=actor.domain,
                    url=emoji_url,
                    static_url=static_url,
                    aliases=tag.get("keywords"),
                    license=license_text,
                    is_sensitive=bool(tag.get("isSensitive", False)),
                    author=tag.get("author") or tag.get("creator"),
                    description=tag.get("description"),
                    copy_permission=tag.get("copyPermission"),
                    usage_info=tag.get("usageInfo"),
                    is_based_on=tag.get("isBasedOn"),
                    category=tag.get("category"),
                )

    # 投票データ
    is_poll = data.get("type") == "Question"
    poll_options = None
    poll_multiple = False
    poll_expires_at = None
    if is_poll:
        one_of = data.get("oneOf")
        any_of = data.get("anyOf")
        choices = any_of or one_of or []
        poll_multiple = any_of is not None
        poll_options = []
        for choice in choices:
            if isinstance(choice, dict):
                title = choice.get("name", "")
                replies = choice.get("replies", {})
                votes = replies.get("totalItems", 0) if isinstance(replies, dict) else 0
                poll_options.append({"title": title, "votes_count": votes})
        end_time = data.get("endTime")
        if end_time:
            from datetime import datetime as dt

            try:
                poll_expires_at = dt.fromisoformat(end_time.replace("Z", "+00:00"))
            except ValueError:
                pass

    note = Note(
        ap_id=note_ap_id,
        actor_id=actor.id,
        content=content,
        source=source,
        visibility=visibility,
        sensitive=data.get("sensitive", False),
        spoiler_text=data.get("summary"),
        to=to_list,
        cc=cc_list,
        in_reply_to_id=in_reply_to_id,
        in_reply_to_ap_id=in_reply_to_ap_id,
        quote_id=quote_id,
        quote_ap_id=quote_ap_id,
        mentions=mentions_list,
        local=False,
        is_poll=is_poll,
        poll_options=poll_options,
        poll_multiple=poll_multiple,
        poll_expires_at=poll_expires_at,
    )

    published = data.get("published")
    if published:
        from datetime import datetime as dt

        try:
            note.published = dt.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            pass

    db.add(note)
    try:
        await db.flush()
    except IntegrityError:
        # 同じap_idのノートがCreate活動とAnnounce活動の競合で既に挿入されている場合、
        # 既存のノートにフォールバックする
        await db.rollback()
        existing = await get_note_by_ap_id(db, ap_id)
        if existing:
            return existing
        return None

    # 添付ファイル処理
    attachments = data.get("attachment", [])
    if isinstance(attachments, dict):
        attachments = [attachments]
    for position, att_data in enumerate(attachments[:4]):
        if not isinstance(att_data, dict):
            continue
        att_type = att_data.get("type", "")
        if att_type not in ("Document", "Image", "Video", "Audio"):
            continue
        att_url = att_data.get("url")
        if isinstance(att_url, list):
            att_url = (
                att_url[0].get("href")
                if att_url and isinstance(att_url[0], dict)
                else (att_url[0] if att_url else None)
            )
        if not att_url or not isinstance(att_url, str):
            continue
        # focalPoint [x, y] をパース
        focal_x, focal_y = None, None
        fp = att_data.get("focalPoint")
        if isinstance(fp, list) and len(fp) >= 2:
            try:
                fx, fy = float(fp[0]), float(fp[1])
                if math.isfinite(fx) and math.isfinite(fy):
                    focal_x = max(-1.0, min(1.0, fx))
                    focal_y = max(-1.0, min(1.0, fy))
            except (ValueError, TypeError):
                pass

        # 動画サムネイル URL 抽出 (AP Document の icon/preview)
        thumb_url = None
        thumb_mime = None
        att_mime = att_data.get("mediaType", "")
        if isinstance(att_mime, str) and att_mime.startswith("video/"):
            icon = att_data.get("icon")
            if isinstance(icon, dict):
                thumb_url = icon.get("url")
                thumb_mime = icon.get("mediaType")
            elif isinstance(icon, str):
                thumb_url = icon
            if not thumb_url:
                preview = att_data.get("preview")
                if isinstance(preview, dict):
                    thumb_url = preview.get("url")
                    thumb_mime = preview.get("mediaType")
                elif isinstance(preview, str):
                    thumb_url = preview
            # http/https 以外のスキームを拒否 (javascript: 等の防止)
            if thumb_url and isinstance(thumb_url, str):
                from urllib.parse import urlparse

                if urlparse(thumb_url).scheme not in ("http", "https"):
                    thumb_url = None

        # 動画の再生時間を抽出 (ISO 8601 duration)
        remote_duration = None
        dur_str = att_data.get("duration")
        if isinstance(dur_str, str):
            remote_duration = _parse_iso_duration(dur_str)

        attachment = NoteAttachment(
            note_id=note.id,
            position=position,
            remote_url=att_url,
            remote_mime_type=att_data.get("mediaType"),
            remote_name=att_data.get("name"),
            remote_blurhash=att_data.get("blurhash"),
            remote_width=att_data.get("width"),
            remote_height=att_data.get("height"),
            remote_description=att_data.get("name"),
            remote_focal_x=focal_x,
            remote_focal_y=focal_y,
            remote_thumbnail_url=thumb_url,
            remote_thumbnail_mime_type=thumb_mime,
            remote_duration=remote_duration,
        )
        db.add(attachment)

    # リモート画像添付ファイルのバックグラウンドフォーカルポイント検出
    if settings.face_detect_enabled:
        await db.flush()
        from sqlalchemy import select as sel

        from app.models.note_attachment import NoteAttachment as NA

        att_rows = await db.execute(
            sel(NA.id).where(
                NA.note_id == note.id,
                NA.remote_url.isnot(None),
                NA.remote_focal_x.is_(None),
                NA.remote_mime_type.in_(
                    ["image/jpeg", "image/png", "image/webp", "image/gif", "image/avif", "image/apng"]
                ),
            )
        )
        att_ids = [row[0] for row in att_rows.all()]
        if att_ids:
            from app.services.face_detect_queue import enqueue_remote

            await enqueue_remote(note.id, att_ids)

    # リモート画像添付ファイルのバックグラウンドタグ付け
    if settings.neko_vision_enabled:
        await db.flush()
        from sqlalchemy import select as sel_v

        from app.models.note_attachment import NoteAttachment as NAV

        att_rows_v = await db.execute(
            sel_v(NAV.id).where(
                NAV.note_id == note.id,
                NAV.remote_url.isnot(None),
                NAV.vision_at.is_(None),
                NAV.remote_mime_type.in_(
                    ["image/jpeg", "image/png", "image/webp", "image/gif",
                     "image/avif", "image/apng"]
                ),
            )
        )
        att_ids_v = [row[0] for row in att_rows_v.all()]
        if att_ids_v:
            from app.services.vision_queue import enqueue_remote as enqueue_vision_remote

            note_text = source or content
            await enqueue_vision_remote(note.id, att_ids_v, note_text=note_text)

    # リモートリプライの親ノートの返信数をインクリメント
    if in_reply_to_id:
        parent = await get_note_by_id(db, in_reply_to_id)
        if parent:
            parent.replies_count = parent.replies_count + 1

    # APタグからハッシュタグを抽出してupsert
    from app.services.hashtag_service import (
        extract_hashtags_from_ap_tags,
    )
    from app.services.hashtag_service import (
        upsert_hashtags as upsert_ht,
    )

    hashtag_names = extract_hashtags_from_ap_tags(tags)
    if hashtag_names:
        await upsert_ht(db, note.id, hashtag_names)

    logger.info("Fetched and stored remote note %s from %s", note_ap_id, actor_ap_id)
    return note
