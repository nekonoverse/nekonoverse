import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.note import Note
from app.models.reaction import Reaction
from app.models.user import User
from app.utils.emoji import is_single_emoji


async def add_reaction(
    db: AsyncSession, user: User, note: Note, emoji: str
) -> Reaction:
    """Add a reaction to a note."""
    if not is_single_emoji(emoji):
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

    # Deliver Like activity to the note's author server
    if not note.actor.is_local:
        from app.activitypub.renderer import render_like_activity
        from app.services.delivery_service import enqueue_delivery

        activity = render_like_activity(ap_id, actor.ap_id, note.ap_id, emoji)
        await enqueue_delivery(db, actor.id, note.actor.inbox_url, activity)

    return reaction


async def remove_reaction(
    db: AsyncSession, user: User, note: Note, emoji: str
):
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

    # Send Undo(Like) to the note's author server
    if not note.actor.is_local and reaction_ap_id:
        from app.activitypub.renderer import render_like_activity, render_undo_activity
        from app.services.delivery_service import enqueue_delivery

        like_activity = render_like_activity(
            reaction_ap_id, actor.ap_id, note.ap_id, emoji
        )
        undo_id = f"{settings.server_url}/activities/{uuid.uuid4()}"
        undo_activity = render_undo_activity(undo_id, actor.ap_id, like_activity)
        await enqueue_delivery(db, actor.id, note.actor.inbox_url, undo_activity)
