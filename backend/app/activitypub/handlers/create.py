"""受信した Create activity を処理する (主に Create Note)。"""

import logging
import math

from sqlalchemy.ext.asyncio import AsyncSession

from app.activitypub import extract_mfm_source
from app.config import settings
from app.models.note import Note
from app.services.actor_service import fetch_remote_actor, get_actor_by_ap_id, get_actors_by_ap_ids
from app.services.note_service import fetch_remote_note, get_note_by_ap_id
from app.utils.sanitize import sanitize_html

logger = logging.getLogger(__name__)


async def handle_create(db: AsyncSession, activity: dict):
    obj = activity.get("object")
    if isinstance(obj, str):
        # オブジェクトが参照形式のためスキップ (フェッチが必要になる)
        logger.info("Create with object reference, skipping: %s", obj)
        return

    if not isinstance(obj, dict):
        return

    obj_type = obj.get("type")
    if obj_type == "Note" and obj.get("name") and obj.get("inReplyTo"):
        # 'name' + 'inReplyTo' を持つ Note は投票への投票 (Mastodon の慣例)
        await _handle_poll_vote(db, activity, obj)
    elif obj_type in ("Note", "Question"):
        await handle_create_note(db, activity, obj)
    else:
        logger.info("Unhandled Create object type: %s", obj_type)


async def handle_create_note(db: AsyncSession, activity: dict, note_data: dict):
    ap_id = note_data.get("id")
    if not ap_id:
        return

    # 既に存在する場合はスキップ
    existing = await get_note_by_ap_id(db, ap_id)
    if existing:
        return

    actor_ap_id = note_data.get("attributedTo") or activity.get("actor")
    if not actor_ap_id:
        return

    # M-1: attributedToとactivity actorのドメイン一致を検証
    activity_actor = activity.get("actor", "")
    if actor_ap_id and activity_actor:
        from urllib.parse import urlparse as _urlparse

        attr_domain = _urlparse(actor_ap_id).hostname
        act_domain = _urlparse(activity_actor).hostname
        if attr_domain and act_domain and attr_domain != act_domain:
            logger.warning(
                "attributedTo domain mismatch: attributedTo=%s actor=%s",
                actor_ap_id,
                activity_actor,
            )
            return

    # アクターを解決
    actor = await get_actor_by_ap_id(db, actor_ap_id)
    if not actor:
        actor = await fetch_remote_actor(db, actor_ap_id)
    if not actor:
        logger.warning("Could not resolve actor %s for note %s", actor_ap_id, ap_id)
        return

    content = sanitize_html(note_data.get("content", ""))
    source = extract_mfm_source(note_data)

    # 公開範囲を決定
    to_list = note_data.get("to", [])
    cc_list = note_data.get("cc", [])
    public = "https://www.w3.org/ns/activitystreams#Public"

    if public in to_list:
        visibility = "public"
    elif public in cc_list:
        visibility = "unlisted"
    elif any(url.endswith("/followers") for url in to_list):
        visibility = "followers"
    else:
        visibility = "direct"

    # プロキシ購読のみの場合、フォロワー限定投稿は保存しない
    # directはフォロー関係ではなく宛先指定で配送されるためフィルタ対象外
    if visibility == "followers" and not actor.is_local:
        from app.services.proxy_service import has_real_local_follower, is_proxy_subscribed

        if await is_proxy_subscribed(db, actor.id) and not await has_real_local_follower(
            db, actor.id
        ):
            logger.debug("Discarding followers-only note %s (proxy-only subscription)", ap_id)
            return

    # リプライと引用を解決
    in_reply_to_ap_id = note_data.get("inReplyTo")
    quote_ap_id = (
        note_data.get("_misskey_quote") or note_data.get("quoteUrl") or note_data.get("quoteUri")
    )

    # ローカルDBを先にチェック
    in_reply_to_id = None
    quote_id = None
    reply_note = await get_note_by_ap_id(db, in_reply_to_ap_id) if in_reply_to_ap_id else None
    quoted_note = await get_note_by_ap_id(db, quote_ap_id) if quote_ap_id else None

    # H-4: ローカルに無い場合のリモートフェッチを並列化
    import asyncio as _asyncio

    fetch_tasks = []
    need_reply_fetch = in_reply_to_ap_id and not reply_note
    need_quote_fetch = quote_ap_id and not quoted_note
    if need_reply_fetch:
        fetch_tasks.append(fetch_remote_note(db, in_reply_to_ap_id))
    if need_quote_fetch:
        fetch_tasks.append(fetch_remote_note(db, quote_ap_id))
    if fetch_tasks:
        results = await _asyncio.gather(*fetch_tasks, return_exceptions=True)
        idx = 0
        if need_reply_fetch:
            r = results[idx]
            if not isinstance(r, Exception):
                reply_note = r
            idx += 1
        if need_quote_fetch:
            r = results[idx]
            if not isinstance(r, Exception):
                quoted_note = r

    if reply_note:
        in_reply_to_id = reply_note.id
    if quoted_note:
        quote_id = quoted_note.id

    # tag 配列からメンションとカスタム絵文字を抽出
    tags = note_data.get("tag", [])
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

                # 拡張フィールドを抽出 (Misskey + CherryPick)
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

    # 投票データをパース (Question タイプ)
    is_poll = note_data.get("type") == "Question"
    poll_options = None
    poll_multiple = False
    poll_expires_at = None

    if is_poll:
        one_of = note_data.get("oneOf")
        any_of = note_data.get("anyOf")
        choices = any_of or one_of or []
        poll_multiple = any_of is not None
        poll_options = []
        for choice in choices:
            if isinstance(choice, dict):
                title = choice.get("name", "")
                replies = choice.get("replies", {})
                votes = replies.get("totalItems", 0) if isinstance(replies, dict) else 0
                poll_options.append({"title": title, "votes_count": votes})

        end_time = note_data.get("endTime")
        if end_time:
            from datetime import datetime

            try:
                poll_expires_at = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            except ValueError:
                pass

    # _misskey_talk をパース
    is_talk = bool(note_data.get("_misskey_talk", False))

    note = Note(
        ap_id=ap_id,
        actor_id=actor.id,
        content=content,
        source=source,
        visibility=visibility,
        sensitive=note_data.get("sensitive", False),
        spoiler_text=note_data.get("summary"),
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
        is_talk=is_talk,
    )

    published = note_data.get("published")
    if published:
        from datetime import datetime

        try:
            note.published = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            pass

    db.add(note)
    await db.flush()

    # 添付ファイルを処理
    attachments = note_data.get("attachment", [])
    if isinstance(attachments, dict):
        attachments = [attachments]

    from app.models.note_attachment import NoteAttachment

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
            from app.services.note_service import _parse_iso_duration

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

    # AP タグからハッシュタグを抽出して upsert
    from app.services.hashtag_service import (
        extract_hashtags_from_ap_tags,
    )
    from app.services.hashtag_service import (
        upsert_hashtags as upsert_ht,
    )

    hashtag_names = extract_hashtags_from_ap_tags(tags)
    if hashtag_names:
        await upsert_ht(db, note.id, hashtag_names)

    # ローカルユーザーへのメンション/リプライ通知
    from app.services.notification_service import create_notification, publish_notification

    pending_notifs = []

    # メンション+リプライ通知の重複を避けるためリプライ先のアクターを特定
    reply_recipient_id = None
    if in_reply_to_id:
        reply_note = await get_note_by_ap_id(db, in_reply_to_ap_id)
        if reply_note:
            # 親ノートの replies_count をインクリメント
            reply_note.replies_count = reply_note.replies_count + 1
            if reply_note.actor and reply_note.actor.is_local and reply_note.actor_id != actor.id:
                reply_recipient_id = reply_note.actor_id
                notif = await create_notification(
                    db,
                    "reply",
                    reply_note.actor_id,
                    actor.id,
                    note.id,
                )
                if notif:
                    pending_notifs.append(notif)

    # メンションアクターをバッチ取得（N+1回避）
    mention_ap_ids = [m["ap_id"] for m in mentions_list if m.get("ap_id")]
    mentioned_actors = await get_actors_by_ap_ids(db, mention_ap_ids) if mention_ap_ids else {}
    for mention in mentions_list:
        mentioned_actor = mentioned_actors.get(mention["ap_id"])
        if (
            mentioned_actor
            and mentioned_actor.is_local
            and mentioned_actor.id != reply_recipient_id
        ):
            notif = await create_notification(
                db,
                "mention",
                mentioned_actor.id,
                actor.id,
                note.id,
            )
            if notif:
                pending_notifs.append(notif)

    await db.commit()
    logger.info("Saved remote note %s from %s", ap_id, actor_ap_id)

    for notif in pending_notifs:
        await publish_notification(notif)

    # リアルタイム SSE ストリーミング用に Valkey に publish
    try:
        import json

        from app.services.follow_service import get_follower_ids
        from app.valkey_client import valkey as valkey_client

        event = json.dumps({"event": "update", "payload": {"id": str(note.id)}})
        # このリモートアクターのフォロワー (フォローしているローカルユーザー) に配信
        # システムアカウントのアクターIDを除外
        from app.services.proxy_service import get_system_actor_ids

        system_ids = await get_system_actor_ids(db)
        follower_ids = await get_follower_ids(db, actor.id)

        # Exclusive リスト: このアクターを exclusive リストに入れているユーザーの
        # ホームTLには配信しない（リストTLにのみ配信）
        from app.services.list_service import (
            get_exclusive_list_user_actor_ids,
            get_list_ids_for_actor,
        )

        exclusive_user_ids = await get_exclusive_list_user_actor_ids(db, actor.id)
        list_ids = await get_list_ids_for_actor(db, actor.id)

        pipe = valkey_client.pipeline()
        if visibility == "public":
            pipe.publish("timeline:public", event)
        for fid in follower_ids:
            if fid not in system_ids and fid not in exclusive_user_ids:
                pipe.publish(f"timeline:home:{fid}", event)
        for lid in list_ids:
            pipe.publish(f"timeline:list:{lid}", event)
        await pipe.execute()
    except Exception:
        logger.exception("Failed to publish remote note to streaming")

    # リモート公開ノートの検索インデックスをキューに追加
    if settings.neko_search_enabled and visibility == "public":
        from app.services.search_queue import enqueue_index

        await enqueue_index(note.id, source or "", note.published)

    # リモート画像添付のバックグラウンドフォーカルポイント検出
    if settings.face_detect_enabled:
        from sqlalchemy import select as sel

        from app.models.note_attachment import NoteAttachment as NA

        att_rows = await db.execute(
            sel(NA.id).where(
                NA.note_id == note.id,
                NA.remote_url.isnot(None),
                NA.remote_focal_x.is_(None),
                NA.remote_mime_type.in_(
                    [
                        "image/jpeg",
                        "image/png",
                        "image/webp",
                        "image/gif",
                        "image/avif",
                        "image/apng",
                    ]
                ),
            )
        )
        att_ids = [row[0] for row in att_rows.all()]
        if att_ids:
            from app.services.face_detect_queue import enqueue_remote

            await enqueue_remote(note.id, att_ids)

    # リモート画像添付のバックグラウンドタグ付け
    if settings.neko_vision_enabled:
        from sqlalchemy import select as sel_v

        from app.models.note_attachment import NoteAttachment as NAV

        att_rows_v = await db.execute(
            sel_v(NAV.id).where(
                NAV.note_id == note.id,
                NAV.remote_url.isnot(None),
                NAV.vision_at.is_(None),
                NAV.remote_mime_type.in_(
                    [
                        "image/jpeg",
                        "image/png",
                        "image/webp",
                        "image/gif",
                        "image/avif",
                        "image/apng",
                    ]
                ),
            )
        )
        att_ids_v = [row[0] for row in att_rows_v.all()]
        if att_ids_v:
            from app.services.vision_queue import enqueue_remote as enqueue_vision_remote

            note_text = source or content
            await enqueue_vision_remote(
                note.id, att_ids_v, note_text=note_text
            )


async def _handle_poll_vote(db: AsyncSession, activity: dict, obj: dict):
    """受信した投票への投票を処理する (name + inReplyTo 付き Create Note)。"""
    in_reply_to = obj.get("inReplyTo")
    option_name = obj.get("name", "").strip()
    if not in_reply_to or not option_name:
        return

    # 投票ノートを検索
    poll_note = await get_note_by_ap_id(db, in_reply_to)
    if not poll_note or not poll_note.is_poll or not poll_note.local:
        logger.debug("Poll vote for unknown/non-local poll: %s", in_reply_to)
        return

    options = poll_note.poll_options or []
    # 一致する選択肢のインデックスを検索
    choice_index = None
    for i, opt in enumerate(options):
        if opt.get("title", "") == option_name:
            choice_index = i
            break

    if choice_index is None:
        logger.debug("Poll vote option '%s' not found in poll %s", option_name, in_reply_to)
        return

    # 投票者アクターを解決
    voter_ap_id = obj.get("attributedTo") or activity.get("actor")
    if not voter_ap_id:
        return

    voter = await get_actor_by_ap_id(db, voter_ap_id)
    if not voter:
        voter = await fetch_remote_actor(db, voter_ap_id)
    if not voter:
        logger.warning("Could not resolve voter actor %s", voter_ap_id)
        return

    # 重複投票をチェック
    from sqlalchemy import select

    from app.models.poll_vote import PollVote

    # M-14: 単一選択投票では同一アクターの既存投票をチェック
    if not poll_note.poll_multiple:
        existing_any = await db.execute(
            select(PollVote).where(
                PollVote.note_id == poll_note.id,
                PollVote.actor_id == voter.id,
            )
        )
        if existing_any.scalars().first():
            logger.debug(
                "Duplicate poll vote (single-choice) from %s on %s",
                voter_ap_id,
                in_reply_to,
            )
            return
    else:
        existing = await db.execute(
            select(PollVote).where(
                PollVote.note_id == poll_note.id,
                PollVote.actor_id == voter.id,
                PollVote.choice_index == choice_index,
            )
        )
        if existing.scalars().first():
            logger.debug("Duplicate poll vote from %s on %s", voter_ap_id, in_reply_to)
            return

    # 投票を記録
    vote = PollVote(
        note_id=poll_note.id,
        actor_id=voter.id,
        choice_index=choice_index,
    )
    db.add(vote)

    # JSONB の得票数を更新
    options[choice_index]["votes_count"] = options[choice_index].get("votes_count", 0) + 1
    from sqlalchemy.orm.attributes import flag_modified

    poll_note.poll_options = list(options)
    flag_modified(poll_note, "poll_options")

    await db.commit()
    logger.info(
        "Recorded poll vote from %s on %s (choice: %s)", voter_ap_id, in_reply_to, option_name
    )
