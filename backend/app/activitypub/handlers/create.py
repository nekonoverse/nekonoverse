"""Handle incoming Create activities (mainly Create Note)."""

import logging
import math

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.note import Note
from app.services.actor_service import fetch_remote_actor, get_actor_by_ap_id
from app.services.note_service import fetch_remote_note, get_note_by_ap_id
from app.utils.sanitize import sanitize_html

logger = logging.getLogger(__name__)


async def handle_create(db: AsyncSession, activity: dict):
    obj = activity.get("object")
    if isinstance(obj, str):
        # Object is a reference, skip for now (would need to fetch)
        logger.info("Create with object reference, skipping: %s", obj)
        return

    if not isinstance(obj, dict):
        return

    obj_type = obj.get("type")
    if obj_type == "Note" and obj.get("name") and obj.get("inReplyTo"):
        # A Note with 'name' + 'inReplyTo' is a poll vote (Mastodon convention)
        await _handle_poll_vote(db, activity, obj)
    elif obj_type in ("Note", "Question"):
        await handle_create_note(db, activity, obj)
    else:
        logger.info("Unhandled Create object type: %s", obj_type)


async def handle_create_note(db: AsyncSession, activity: dict, note_data: dict):
    ap_id = note_data.get("id")
    if not ap_id:
        return

    # Skip if already exists
    existing = await get_note_by_ap_id(db, ap_id)
    if existing:
        return

    actor_ap_id = note_data.get("attributedTo") or activity.get("actor")
    if not actor_ap_id:
        return

    # Resolve actor
    actor = await get_actor_by_ap_id(db, actor_ap_id)
    if not actor:
        actor = await fetch_remote_actor(db, actor_ap_id)
    if not actor:
        logger.warning("Could not resolve actor %s for note %s", actor_ap_id, ap_id)
        return

    content = sanitize_html(note_data.get("content", ""))
    source_data = note_data.get("source")
    source = None
    if isinstance(source_data, dict):
        source = source_data.get("content")

    # Misskey fallback: _misskey_content
    if source is None:
        misskey_content = note_data.get("_misskey_content")
        if isinstance(misskey_content, str):
            source = misskey_content

    # Determine visibility
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

    # Resolve reply
    in_reply_to_ap_id = note_data.get("inReplyTo")
    in_reply_to_id = None
    if in_reply_to_ap_id:
        reply_note = await get_note_by_ap_id(db, in_reply_to_ap_id)
        # ローカルに無ければリモートからfetch
        if not reply_note:
            reply_note = await fetch_remote_note(db, in_reply_to_ap_id)
        if reply_note:
            in_reply_to_id = reply_note.id

    # Resolve quote (Misskey-style)
    quote_ap_id = (
        note_data.get("_misskey_quote") or note_data.get("quoteUrl") or note_data.get("quoteUri")
    )
    quote_id = None
    if quote_ap_id:
        quoted_note = await get_note_by_ap_id(db, quote_ap_id)
        # ローカルに無ければリモートからfetch
        if not quoted_note:
            quoted_note = await fetch_remote_note(db, quote_ap_id)
        if quoted_note:
            quote_id = quoted_note.id

    # Extract mentions and custom emoji from tag array
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

                # Extract extended fields (Misskey + CherryPick)
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

    # Parse poll data (Question type)
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

    # Parse _misskey_talk
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

    # Process attachments
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

        # Parse focalPoint [x, y]
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
        )
        db.add(attachment)

    # Extract and upsert hashtags from AP tags
    from app.services.hashtag_service import (
        extract_hashtags_from_ap_tags,
    )
    from app.services.hashtag_service import (
        upsert_hashtags as upsert_ht,
    )

    hashtag_names = extract_hashtags_from_ap_tags(tags)
    if hashtag_names:
        await upsert_ht(db, note.id, hashtag_names)

    # Mention/reply notifications for local users
    from app.services.notification_service import create_notification, publish_notification

    pending_notifs = []
    for mention in mentions_list:
        mentioned_actor = await get_actor_by_ap_id(db, mention["ap_id"])
        if mentioned_actor and mentioned_actor.is_local:
            notif = await create_notification(
                db, "mention", mentioned_actor.id, actor.id, note.id,
            )
            if notif:
                pending_notifs.append(notif)

    if in_reply_to_id:
        reply_note = await get_note_by_ap_id(db, in_reply_to_ap_id)
        if reply_note and reply_note.actor and reply_note.actor.is_local and reply_note.actor_id != actor.id:
            notif = await create_notification(
                db, "reply", reply_note.actor_id, actor.id, note.id,
            )
            if notif:
                pending_notifs.append(notif)

    await db.commit()
    logger.info("Saved remote note %s from %s", ap_id, actor_ap_id)

    for notif in pending_notifs:
        await publish_notification(notif)

    # Publish to Valkey for real-time SSE streaming
    try:
        import json

        from app.services.follow_service import get_follower_ids
        from app.valkey_client import valkey as valkey_client

        event = json.dumps({"event": "update", "payload": {"id": str(note.id)}})
        if visibility == "public":
            await valkey_client.publish("timeline:public", event)
        # Deliver to followers of this remote actor (local users who follow them)
        follower_ids = await get_follower_ids(db, actor.id)
        for fid in follower_ids:
            await valkey_client.publish(f"timeline:home:{fid}", event)
    except Exception:
        logger.exception("Failed to publish remote note to streaming")

    # Background focal point detection for remote image attachments
    if settings.face_detect_url:
        from sqlalchemy import select as sel

        from app.models.note_attachment import NoteAttachment as NA

        att_rows = await db.execute(
            sel(NA.id).where(
                NA.note_id == note.id,
                NA.remote_url.isnot(None),
                NA.remote_focal_x.is_(None),
                NA.remote_mime_type.in_(
                    ["image/jpeg", "image/png", "image/webp", "image/gif", "image/avif"]
                ),
            )
        )
        att_ids = [row[0] for row in att_rows.all()]
        if att_ids:
            from app.services.face_detect_queue import enqueue_remote

            await enqueue_remote(note.id, att_ids)


async def _handle_poll_vote(db: AsyncSession, activity: dict, obj: dict):
    """Handle an incoming poll vote (Create Note with name + inReplyTo)."""
    in_reply_to = obj.get("inReplyTo")
    option_name = obj.get("name", "").strip()
    if not in_reply_to or not option_name:
        return

    # Find the poll note
    poll_note = await get_note_by_ap_id(db, in_reply_to)
    if not poll_note or not poll_note.is_poll or not poll_note.local:
        logger.debug("Poll vote for unknown/non-local poll: %s", in_reply_to)
        return

    options = poll_note.poll_options or []
    # Find matching option index
    choice_index = None
    for i, opt in enumerate(options):
        if opt.get("title", "") == option_name:
            choice_index = i
            break

    if choice_index is None:
        logger.debug("Poll vote option '%s' not found in poll %s", option_name, in_reply_to)
        return

    # Resolve voter actor
    voter_ap_id = obj.get("attributedTo") or activity.get("actor")
    if not voter_ap_id:
        return

    voter = await get_actor_by_ap_id(db, voter_ap_id)
    if not voter:
        voter = await fetch_remote_actor(db, voter_ap_id)
    if not voter:
        logger.warning("Could not resolve voter actor %s", voter_ap_id)
        return

    # Check for duplicate vote
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
                voter_ap_id, in_reply_to,
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

    # Record vote
    vote = PollVote(
        note_id=poll_note.id,
        actor_id=voter.id,
        choice_index=choice_index,
    )
    db.add(vote)

    # Update JSONB vote count
    options[choice_index]["votes_count"] = options[choice_index].get("votes_count", 0) + 1
    from sqlalchemy.orm.attributes import flag_modified

    poll_note.poll_options = list(options)
    flag_modified(poll_note, "poll_options")

    await db.commit()
    logger.info("Recorded poll vote from %s on %s (choice: %s)", voter_ap_id, in_reply_to, option_name)
