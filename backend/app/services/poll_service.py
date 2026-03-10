"""Poll service: create poll notes, vote, get results."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.poll_vote import PollVote
from app.models.user import User
from app.services.note_service import get_note_by_id


async def vote_on_poll(
    db: AsyncSession,
    user: User,
    note_id: uuid.UUID,
    choices: list[int],
) -> None:
    """Cast votes on a poll. Raises ValueError on invalid input."""
    note = await get_note_by_id(db, note_id)
    if not note:
        raise ValueError("Note not found")
    if not note.is_poll:
        raise ValueError("Not a poll")

    options = note.poll_options or []
    if not options:
        raise ValueError("Poll has no options")

    # Check expiry
    if note.poll_expires_at and note.poll_expires_at < datetime.now(timezone.utc):
        raise ValueError("Poll has expired")

    # Validate choices
    if not note.poll_multiple and len(choices) > 1:
        raise ValueError("Multiple choices not allowed")

    for idx in choices:
        if idx < 0 or idx >= len(options):
            raise ValueError(f"Invalid choice index: {idx}")

    actor = user.actor

    # Check for existing votes
    existing = await db.execute(
        select(PollVote).where(
            PollVote.note_id == note_id,
            PollVote.actor_id == actor.id,
        )
    )
    if existing.scalars().first():
        raise ValueError("Already voted")

    # Create votes and update counts
    for idx in choices:
        vote = PollVote(
            note_id=note_id,
            actor_id=actor.id,
            choice_index=idx,
        )
        db.add(vote)

        # Update vote count in poll_options
        options[idx]["votes_count"] = options[idx].get("votes_count", 0) + 1

    # Force JSONB update detection
    from sqlalchemy.orm.attributes import flag_modified

    note.poll_options = list(options)
    flag_modified(note, "poll_options")
    await db.flush()


async def get_poll_data(
    db: AsyncSession,
    note_id: uuid.UUID,
    current_actor_id: uuid.UUID | None = None,
) -> dict | None:
    """Get poll data for a note. Returns None if not a poll."""
    note = await get_note_by_id(db, note_id)
    if not note or not note.is_poll:
        return None

    options = note.poll_options or []
    votes_count = sum(opt.get("votes_count", 0) for opt in options)

    # Count unique voters
    from sqlalchemy import func

    voters_result = await db.execute(
        select(func.count(func.distinct(PollVote.actor_id))).where(PollVote.note_id == note_id)
    )
    voters_count = voters_result.scalar() or 0

    expired = False
    if note.poll_expires_at:
        expired = note.poll_expires_at < datetime.now(timezone.utc)

    own_votes: list[int] = []
    voted = False
    if current_actor_id:
        result = await db.execute(
            select(PollVote.choice_index).where(
                PollVote.note_id == note_id,
                PollVote.actor_id == current_actor_id,
            )
        )
        own_votes = [row[0] for row in result.all()]
        voted = len(own_votes) > 0

    return {
        "id": str(note_id),
        "expires_at": note.poll_expires_at.isoformat() if note.poll_expires_at else None,
        "expired": expired,
        "multiple": note.poll_multiple,
        "votes_count": votes_count,
        "voters_count": voters_count,
        "options": [
            {"title": opt.get("title", ""), "votes_count": opt.get("votes_count", 0)}
            for opt in options
        ],
        "voted": voted,
        "own_votes": own_votes,
    }
