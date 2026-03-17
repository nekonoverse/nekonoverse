import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.note import Note
from app.models.reaction import Reaction
from app.models.user import User
from app.services.actor_service import actor_uri
from app.utils.emoji import is_custom_emoji_shortcode, is_single_emoji


async def _publish_reaction_event(db: AsyncSession, note: Note) -> None:
    """Publish a real-time reaction event via Valkey pub/sub."""
    try:
        import json

        from app.services.follow_service import get_follower_ids
        from app.valkey_client import valkey as valkey_client

        event = json.dumps(
            {
                "event": "status.reaction",
                "payload": {"id": str(note.id)},
            }
        )

        if note.visibility == "public":
            await valkey_client.publish("timeline:public", event)

        await valkey_client.publish(f"timeline:home:{note.actor_id}", event)

        follower_ids = await get_follower_ids(db, note.actor_id)
        for fid in follower_ids:
            await valkey_client.publish(f"timeline:home:{fid}", event)
    except Exception:
        pass


async def add_reaction(db: AsyncSession, user: User, note: Note, emoji: str) -> Reaction:
    """Add a reaction to a note."""
    if not is_single_emoji(emoji) and not is_custom_emoji_shortcode(emoji):
        raise ValueError("Invalid emoji")

    actor = user.actor

    # Check for duplicate
    existing = await db.execute(
        select(Reaction).where(
            Reaction.actor_id == actor.id,
            Reaction.note_id == note.id,
            Reaction.emoji == emoji,
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("Already reacted with this emoji")

    reaction_id = uuid.uuid4()
    ap_id = f"{settings.server_url}/activities/{reaction_id}"

    reaction = Reaction(
        id=reaction_id,
        ap_id=ap_id,
        actor_id=actor.id,
        note_id=note.id,
        emoji=emoji,
    )
    db.add(reaction)
    note.reactions_count += 1
    # L-11: 競合状態対策 -- DB一意制約違反時は既存リアクションとして扱う
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise ValueError("Already reacted with this emoji")

    await _publish_reaction_event(db, note)

    # Build activities for federation
    from app.activitypub.renderer import (
        render_emoji_react_activity,
        render_like_activity,
    )
    from app.services.delivery_service import enqueue_delivery
    from app.services.follow_service import get_follower_inboxes

    is_favourite = emoji == "\u2b50"

    like_activity = render_like_activity(ap_id, actor_uri(actor), note.ap_id, emoji)
    react_activity = None
    if not is_favourite:
        react_id = f"{settings.server_url}/activities/{uuid.uuid4()}"
        react_activity = render_emoji_react_activity(
            react_id, actor_uri(actor), note.ap_id, emoji
        )

    # Attach emoji tag for custom emoji so remote server can display it
    if is_custom_emoji_shortcode(emoji):
        import re

        sc_match = re.match(r"^:([a-zA-Z0-9_]+)(?:@([a-zA-Z0-9.-]+))?:", emoji)
        if sc_match:
            from app.services.emoji_service import get_custom_emoji

            shortcode = sc_match.group(1)
            domain = sc_match.group(2)

            emoji_obj = await get_custom_emoji(db, shortcode, None)
            if not emoji_obj and domain:
                emoji_obj = await get_custom_emoji(db, shortcode, domain)

            if emoji_obj:
                emoji_tag = [
                    {
                        "id": emoji_obj.url,
                        "type": "Emoji",
                        "name": f":{emoji_obj.shortcode}:",
                        "icon": {
                            "type": "Image",
                            "mediaType": "image/png",
                            "url": emoji_obj.url,
                        },
                    }
                ]
                like_activity["tag"] = emoji_tag
                if react_activity:
                    react_activity["tag"] = emoji_tag

                bare = f":{emoji_obj.shortcode}:"
                like_activity["content"] = bare
                like_activity["_misskey_reaction"] = bare
                if react_activity:
                    react_activity["content"] = bare

    # Collect target inboxes: note author + reactor's followers
    inboxes: set[str] = set()
    if not note.actor.is_local:
        inboxes.add(note.actor.shared_inbox_url or note.actor.inbox_url)
    follower_inboxes = await get_follower_inboxes(db, actor.id)
    inboxes.update(follower_inboxes)

    from urllib.parse import urlparse

    from app.utils.nodeinfo import supports_emoji_reactions, uses_emoji_react

    for inbox_url in inboxes:
        domain = urlparse(inbox_url).hostname
        if is_favourite:
            # ☆ favourite → Like to all servers
            await enqueue_delivery(db, actor.id, inbox_url, like_activity)
        elif domain and await uses_emoji_react(domain):
            # EmojiReact-capable (Neko/Pleroma/Akkoma/Fedibird) → EmojiReact
            await enqueue_delivery(db, actor.id, inbox_url, react_activity)
        elif domain and await supports_emoji_reactions(domain):
            # Misskey-compatible → Like + _misskey_reaction
            await enqueue_delivery(db, actor.id, inbox_url, like_activity)
        # else: Mastodon/GoToSocial/unknown → don't send emoji reactions

    return reaction


async def remove_reaction(db: AsyncSession, user: User, note: Note, emoji: str):
    """Remove a reaction from a note."""
    actor = user.actor

    result = await db.execute(
        select(Reaction).where(
            Reaction.actor_id == actor.id,
            Reaction.note_id == note.id,
            Reaction.emoji == emoji,
        )
    )
    reaction = result.scalar_one_or_none()
    if not reaction:
        raise ValueError("Reaction not found")

    reaction_ap_id = reaction.ap_id

    await db.delete(reaction)
    note.reactions_count = max(0, note.reactions_count - 1)
    await db.commit()

    await _publish_reaction_event(db, note)

    # Send Undo to observing servers (mirrors add_reaction routing)
    if reaction_ap_id:
        from app.activitypub.renderer import (
            render_emoji_react_activity,
            render_like_activity,
            render_undo_activity,
        )
        from app.services.delivery_service import enqueue_delivery
        from app.services.follow_service import get_follower_inboxes

        is_favourite = emoji == "\u2b50"

        like_activity = render_like_activity(
            reaction_ap_id, actor_uri(actor), note.ap_id, emoji
        )
        undo_like_id = f"{settings.server_url}/activities/{uuid.uuid4()}"
        undo_like = render_undo_activity(undo_like_id, actor_uri(actor), like_activity)

        undo_react = None
        if not is_favourite:
            react_activity = render_emoji_react_activity(
                f"{reaction_ap_id}/react", actor_uri(actor), note.ap_id, emoji
            )
            undo_react_id = f"{settings.server_url}/activities/{uuid.uuid4()}"
            undo_react = render_undo_activity(
                undo_react_id, actor_uri(actor), react_activity
            )

        inboxes: set[str] = set()
        if not note.actor.is_local:
            inboxes.add(note.actor.shared_inbox_url or note.actor.inbox_url)
        follower_inboxes = await get_follower_inboxes(db, actor.id)
        inboxes.update(follower_inboxes)

        from urllib.parse import urlparse

        from app.utils.nodeinfo import supports_emoji_reactions, uses_emoji_react

        for inbox_url in inboxes:
            domain = urlparse(inbox_url).hostname
            if is_favourite:
                # ☆ favourite → Undo(Like) to all servers
                await enqueue_delivery(db, actor.id, inbox_url, undo_like)
            elif domain and await uses_emoji_react(domain):
                # EmojiReact-capable → Undo(EmojiReact)
                await enqueue_delivery(db, actor.id, inbox_url, undo_react)
            elif domain and await supports_emoji_reactions(domain):
                # Misskey-compatible → Undo(Like)
                await enqueue_delivery(db, actor.id, inbox_url, undo_like)
            # else: Mastodon/GoToSocial/unknown → nothing was sent, nothing to undo
