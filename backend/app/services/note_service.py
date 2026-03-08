import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.actor import Actor
from app.models.note import Note
from app.models.reaction import Reaction
from app.models.user import User
from app.utils.sanitize import MENTION_PATTERN, text_to_html

_EMOJI_SHORTCODE_RE = re.compile(r":([a-zA-Z0-9_]+):")
_CUSTOM_EMOJI_REACTION_RE = re.compile(r"^:([a-zA-Z0-9_]+)(?:@([a-zA-Z0-9.-]+))?:$")


def extract_mentions(text: str) -> list[tuple[str, str | None]]:
    """Extract (username, domain) tuples from text. domain is None for local."""
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
    actor = user.actor
    note_id = uuid.uuid4()
    ap_id = f"{settings.server_url}/notes/{note_id}"

    # Build to/cc based on visibility
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
    # direct: to/cc set to mentioned actors only (handled later)

    # Extract mentions and add to cc/to
    mentions = extract_mentions(content)
    mention_data = []
    for username, domain in mentions:
        from app.services.actor_service import actor_uri, get_actor_by_username
        mentioned_actor = await get_actor_by_username(db, username, domain)
        # リモートユーザーがDBに未登録の場合、WebFingerで解決
        if not mentioned_actor and domain:
            from app.services.actor_service import resolve_webfinger
            mentioned_actor = await resolve_webfinger(db, username, domain)
        if mentioned_actor:
            mentioned_uri = actor_uri(mentioned_actor)
            mention_data.append({
                "ap_id": mentioned_uri,
                "username": mentioned_actor.username,
                "domain": mentioned_actor.domain,
            })
            if visibility == "direct":
                if mentioned_uri not in to_list:
                    to_list.append(mentioned_uri)
            else:
                if mentioned_uri not in cc_list:
                    cc_list.append(mentioned_uri)

    html_content = text_to_html(content)

    # Resolve quote
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
        mentions=mention_data,
        quote_id=quote_id,
        quote_ap_id=quote_ap_id,
    )

    # Poll support
    if poll_options:
        from datetime import datetime, timedelta, timezone
        note.is_poll = True
        note.poll_options = [{"title": opt, "votes_count": 0} for opt in poll_options]
        note.poll_multiple = poll_multiple
        if poll_expires_in:
            note.poll_expires_at = datetime.now(timezone.utc) + timedelta(seconds=poll_expires_in)
    db.add(note)

    # Attach media files
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

    # Reload note with all relationships for rendering and response
    note = await get_note_by_id(db, note_id)

    # Extract custom emoji shortcodes for AP federation tags
    shortcodes = set(_EMOJI_SHORTCODE_RE.findall(content))
    if shortcodes:
        from app.services.emoji_service import get_custom_emoji
        emoji_tags = []
        for sc in shortcodes:
            emoji = await get_custom_emoji(db, sc, None)
            if emoji and not emoji.local_only:
                emoji_tags.append({
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
                })
        if emoji_tags:
            note._emoji_tags = emoji_tags

    # Deliver to followers and mentioned remote users
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

        for inbox_url in inboxes:
            await enqueue_delivery(db, actor.id, inbox_url, activity)

    # Send notifications
    from app.services.notification_service import create_notification

    # Mention notifications (local actors only)
    for m in mention_data:
        if not m.get("domain"):  # local actor
            from app.services.actor_service import get_actor_by_username
            mentioned = await get_actor_by_username(db, m["username"], None)
            if mentioned:
                await create_notification(
                    db, "mention", mentioned.id, actor.id, note_id,
                )

    # Reply notification
    if in_reply_to_id:
        parent = await get_note_by_id(db, in_reply_to_id)
        if parent and parent.actor.is_local:
            await create_notification(
                db, "reply", parent.actor_id, actor.id, note_id,
            )

    await db.commit()

    # Publish real-time events via Valkey pub/sub
    try:
        import json

        from app.services.follow_service import get_follower_ids
        from app.valkey_client import valkey as valkey_client

        event = json.dumps({"event": "update", "payload": {"id": str(note_id)}})
        if visibility in ("public", "unlisted"):
            await valkey_client.publish("timeline:public", event)
        follower_ids = await get_follower_ids(db, actor.id)
        for fid in follower_ids:
            await valkey_client.publish(f"timeline:home:{fid}", event)
        await valkey_client.publish(f"timeline:home:{actor.id}", event)
    except Exception:
        pass  # Don't fail note creation if pub/sub fails

    # Re-query after delivery commits to get fresh state
    return await get_note_by_id(db, note_id)


def _note_load_options():
    """Standard eager-loading options for Note queries."""
    return [
        selectinload(Note.actor),
        selectinload(Note.attachments),
        selectinload(Note.quoted_note).selectinload(Note.actor),
        selectinload(Note.quoted_note).selectinload(Note.attachments),
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
    """Check whether the current user is allowed to see this note."""
    if note.visibility in ("public", "unlisted"):
        return True
    if not current_actor_id:
        return False
    # Author can always see their own notes
    if note.actor_id == current_actor_id:
        return True
    if note.visibility == "followers":
        from app.models.follow import Follow
        result = await db.execute(
            select(Follow.id).where(
                Follow.following_id == note.actor_id,
                Follow.follower_id == current_actor_id,
                Follow.accepted.is_(True),
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None
    if note.visibility == "direct":
        from app.models.actor import Actor
        result = await db.execute(
            select(Actor.ap_id).where(Actor.id == current_actor_id)
        )
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
    """Get IDs of actors blocked or muted by the given actor."""
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
    if max_id:
        # Get the published time of max_id note for cursor pagination
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

    # Get IDs of actors this user follows
    following_result = await db.execute(
        select(Follow.following_id).where(
            Follow.follower_id == actor_id,
            Follow.accepted.is_(True),
        )
    )
    following_ids = [row[0] for row in following_result.all()]
    # Include self
    following_ids.append(actor_id)

    # Exclude blocked/muted actors
    excluded = await _get_excluded_ids(db, actor_id)
    visible_ids = [fid for fid in following_ids if fid not in excluded]

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
    """Get aggregated reactions for a note."""
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

        # Resolve custom emoji URL (prefer local version)
        emoji_url = None
        m = _CUSTOM_EMOJI_REACTION_RE.match(emoji)
        if m:
            from app.services.emoji_service import get_custom_emoji
            shortcode, domain = m.group(1), m.group(2)
            local = await get_custom_emoji(db, shortcode, None)
            if local:
                emoji_url = local.url
            elif domain:
                remote = await get_custom_emoji(db, shortcode, domain)
                if remote:
                    emoji_url = remote.url

        from app.utils.media_proxy import media_proxy_url
        summaries.append({"emoji": emoji, "count": count, "me": me, "emoji_url": media_proxy_url(emoji_url)})
    return summaries
