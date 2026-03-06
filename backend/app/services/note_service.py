import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.actor import Actor
from app.models.note import Note
from app.models.reaction import Reaction
from app.models.user import User
from app.utils.sanitize import text_to_html


async def create_note(
    db: AsyncSession,
    user: User,
    content: str,
    visibility: str = "public",
    sensitive: bool = False,
    spoiler_text: str | None = None,
    in_reply_to_id: uuid.UUID | None = None,
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

    html_content = text_to_html(content)

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
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)

    # Deliver to followers (public/unlisted/followers visibility)
    if visibility in ("public", "unlisted", "followers"):
        from app.activitypub.renderer import render_create_activity
        from app.services.delivery_service import enqueue_delivery
        from app.services.follow_service import get_follower_inboxes

        # Need to reload actor relationship for rendering
        await db.refresh(note, ["actor"])
        activity = render_create_activity(note)
        inboxes = await get_follower_inboxes(db, actor.id)
        for inbox_url in inboxes:
            await enqueue_delivery(db, actor.id, inbox_url, activity)

    return note


async def get_note_by_id(db: AsyncSession, note_id: uuid.UUID) -> Note | None:
    result = await db.execute(
        select(Note)
        .options(selectinload(Note.actor))
        .where(Note.id == note_id, Note.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def get_note_by_ap_id(db: AsyncSession, ap_id: str) -> Note | None:
    result = await db.execute(
        select(Note)
        .options(selectinload(Note.actor))
        .where(Note.ap_id == ap_id, Note.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def get_public_timeline(
    db: AsyncSession,
    limit: int = 20,
    max_id: uuid.UUID | None = None,
    local_only: bool = False,
) -> list[Note]:
    query = (
        select(Note)
        .options(selectinload(Note.actor))
        .where(Note.visibility == "public", Note.deleted_at.is_(None))
    )
    if local_only:
        query = query.where(Note.local.is_(True))
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

    query = (
        select(Note)
        .options(selectinload(Note.actor))
        .where(
            Note.actor_id.in_(following_ids),
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
        summaries.append({"emoji": emoji, "count": count, "me": me})
    return summaries
