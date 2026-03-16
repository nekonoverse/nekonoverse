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
    await db.commit()

    await _publish_reaction_event(db, note)

    # Build Like (Misskey) + EmojiReact (Fedibird/Pleroma/Akkoma) activities
    from app.activitypub.renderer import (
        render_emoji_react_activity,
        render_like_activity,
    )
    from app.services.delivery_service import enqueue_delivery
    from app.services.follow_service import get_follower_inboxes

    like_activity = render_like_activity(ap_id, actor_uri(actor), note.ap_id, emoji)
    react_id = f"{settings.server_url}/activities/{uuid.uuid4()}"
    react_activity = render_emoji_react_activity(
        react_id, actor_uri(actor), note.ap_id, emoji
    )

    # Attach emoji tag for custom emoji so remote server can display it
    if is_custom_emoji_shortcode(emoji):
        import re

        sc_match = re.match(r"^:([a-zA-Z0-9_]+):", emoji)
        if sc_match:
            from app.services.emoji_service import get_custom_emoji

            local_emoji = await get_custom_emoji(db, sc_match.group(1), None)
            if local_emoji:
                emoji_tag = [
                    {
                        "type": "Emoji",
                        "name": f":{local_emoji.shortcode}:",
                        "icon": {
                            "type": "Image",
                            "mediaType": "image/png",
                            "url": local_emoji.url,
                        },
                    }
                ]
                like_activity["tag"] = emoji_tag
                react_activity["tag"] = emoji_tag

    # Collect target inboxes: note author + reactor's followers
    inboxes: set[str] = set()
    if not note.actor.is_local:
        inboxes.add(note.actor.shared_inbox_url or note.actor.inbox_url)
    follower_inboxes = await get_follower_inboxes(db, actor.id)
    inboxes.update(follower_inboxes)

    for inbox_url in inboxes:
        await enqueue_delivery(db, actor.id, inbox_url, like_activity)
        await enqueue_delivery(db, actor.id, inbox_url, react_activity)

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

    # Send Undo(Like) + Undo(EmojiReact) to all observing servers
    if reaction_ap_id:
        from app.activitypub.renderer import (
            render_emoji_react_activity,
            render_like_activity,
            render_undo_activity,
        )
        from app.services.delivery_service import enqueue_delivery
        from app.services.follow_service import get_follower_inboxes

        like_activity = render_like_activity(
            reaction_ap_id, actor_uri(actor), note.ap_id, emoji
        )
        undo_like_id = f"{settings.server_url}/activities/{uuid.uuid4()}"
        undo_like = render_undo_activity(undo_like_id, actor_uri(actor), like_activity)

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

        for inbox_url in inboxes:
            await enqueue_delivery(db, actor.id, inbox_url, undo_like)
            await enqueue_delivery(db, actor.id, inbox_url, undo_react)
