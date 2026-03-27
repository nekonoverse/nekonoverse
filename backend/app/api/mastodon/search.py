from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.actor import Actor
from app.models.hashtag import Hashtag
from app.models.note import Note
from app.models.user import User
from app.services.note_service import _note_load_options, get_reaction_summaries

router = APIRouter(prefix="/api/v2", tags=["search"])


def _escape_like(value: str) -> str:
    """Escape special characters for LIKE/ILIKE patterns."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/search")
async def search(
    q: str = Query(min_length=1),
    type: str | None = Query(default=None, alias="type"),
    resolve: bool = False,
    limit: int = Query(default=20, ge=1, le=40),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Unified search across accounts, statuses, and hashtags (auth required)."""
    accounts = []
    statuses = []
    hashtags = []

    search_accounts = type is None or type == "accounts"
    search_statuses = type is None or type == "statuses"
    search_hashtags = type is None or type == "hashtags"

    if search_accounts:
        accounts = await _search_accounts(db, q, resolve, limit)

    if search_statuses:
        actor_id = user.actor_id
        statuses = await _search_statuses(db, q, limit, actor_id, resolve)

    if search_hashtags:
        hashtags = await _search_hashtags(db, q, limit)

    return {
        "accounts": accounts,
        "statuses": statuses,
        "hashtags": hashtags,
    }


async def _search_accounts(
    db: AsyncSession, q: str, resolve: bool, limit: int
) -> list[dict]:
    """Search for accounts by username or display_name."""
    from app.api.mastodon.accounts import _actor_to_account

    query_str = q.lstrip("@")
    accounts = []

    # user@domain形式の場合
    if "@" in query_str:
        username, domain = query_str.split("@", 1)
        from app.services.actor_service import get_actor_by_username

        actor = await get_actor_by_username(db, username, domain)

        if not actor and resolve:
            from app.services.actor_service import resolve_webfinger

            actor = await resolve_webfinger(db, username, domain)

        if actor:
            accounts.append(await _actor_to_account(actor, db=db))
    else:
        # ユーザー名またはdisplay_nameでILIKE検索
        pattern = f"%{_escape_like(query_str)}%"
        result = await db.execute(
            select(Actor)
            .where(
                Actor.silenced_at.is_(None),
                (Actor.username.ilike(pattern) | Actor.display_name.ilike(pattern)),
            )
            .order_by(Actor.domain.is_(None).desc(), Actor.username)
            .limit(limit)
        )
        actors = result.scalars().all()
        for actor in actors:
            accounts.append(await _actor_to_account(actor, db=db))

    return accounts


async def _search_statuses(
    db: AsyncSession,
    q: str,
    limit: int,
    current_actor_id=None,
    resolve: bool = False,
) -> list[dict]:
    """Search public statuses by content or resolve by URL."""
    from app.api.mastodon.statuses import notes_to_responses

    # URL形式の場合はリモートノート照会を試みる
    url = q.strip()
    if resolve and url.startswith("https://"):
        from app.services.note_service import fetch_remote_note, get_note_by_ap_id

        note = await get_note_by_ap_id(db, url)
        if not note:
            try:
                note = await fetch_remote_note(db, url)
            except Exception:
                pass
        if note:
            # Re-query with eager loading for notes_to_responses
            result = await db.execute(
                select(Note)
                .options(*_note_load_options())
                .where(Note.id == note.id)
            )
            note = result.scalar_one_or_none()
        if note:
            reactions_map = await get_reaction_summaries(
                db, [note.id], current_actor_id
            )
            return await notes_to_responses(
                [note], reactions_map, db, actor_id=current_actor_id
            )
        return []

    # Use neko-search if available
    if settings.neko_search_enabled:
        neko_results = await _search_via_neko_search(q, limit)
        if neko_results is not None:
            notes = await _fetch_notes_by_ids(db, neko_results)
            if notes:
                note_ids = [n.id for n in notes]
                reactions_map = await get_reaction_summaries(db, note_ids, current_actor_id)
                return await notes_to_responses(
                    notes, reactions_map, db, actor_id=current_actor_id
                )
            return []

    # Fallback: ILIKE search
    pattern = f"%{_escape_like(q)}%"
    query = (
        select(Note)
        .join(Actor, Note.actor_id == Actor.id)
        .options(*_note_load_options())
        .where(
            Note.deleted_at.is_(None),
            Note.visibility == "public",
            Actor.silenced_at.is_(None),
            (Note.source.ilike(pattern) | Note.content.ilike(pattern)),
        )
        .order_by(Note.published.desc())
        .limit(limit)
    )
    result = await db.execute(query)
    notes = list(result.scalars().all())

    if not notes:
        return []

    note_ids = [n.id for n in notes]
    reactions_map = await get_reaction_summaries(db, note_ids, current_actor_id)
    return await notes_to_responses(
        notes, reactions_map, db, actor_id=current_actor_id
    )


async def _search_via_neko_search(q: str, limit: int) -> list[str] | None:
    """Call neko-search API. Returns list of note_id strings or None on failure."""
    import logging

    from app.utils.http_client import make_neko_search_client

    logger = logging.getLogger(__name__)
    base = settings.neko_search_base_url.rstrip("/")
    try:
        async with make_neko_search_client() as client:
            resp = await client.get(f"{base}/search", params={"q": q, "limit": limit})
            resp.raise_for_status()
            data = resp.json()
            return data.get("note_ids", [])
    except Exception:
        logger.warning("neko-search unavailable, falling back to ILIKE", exc_info=True)
        return None


async def _fetch_notes_by_ids(db: AsyncSession, note_id_strs: list[str]) -> list:
    """Fetch notes by ID strings, preserving order from search results."""
    import uuid

    try:
        uuids = [uuid.UUID(nid) for nid in note_id_strs]
    except ValueError:
        return []

    if not uuids:
        return []

    result = await db.execute(
        select(Note)
        .join(Actor, Note.actor_id == Actor.id)
        .options(*_note_load_options())
        .where(
            Note.id.in_(uuids),
            Note.deleted_at.is_(None),
            Actor.silenced_at.is_(None),
        )
    )
    notes_by_id = {n.id: n for n in result.scalars().all()}
    # Preserve search ranking order
    return [notes_by_id[uid] for uid in uuids if uid in notes_by_id]


@router.get("/search/suggest")
async def suggest(
    q: str = Query(min_length=1),
    limit: int = Query(default=10, ge=1, le=50),
    _user: User = Depends(get_current_user),
):
    """Proxy suggest requests to neko-search (auth required)."""
    if not settings.neko_search_enabled:
        return {"suggestions": [], "prefix": ""}

    result = await _suggest_via_neko_search(q, limit)
    if result is None:
        return {"suggestions": [], "prefix": ""}
    return result


async def _suggest_via_neko_search(q: str, limit: int) -> dict | None:
    """Call neko-search /suggest API. Returns response dict or None on failure."""
    import logging

    from app.utils.http_client import make_neko_search_client

    logger = logging.getLogger(__name__)
    base = settings.neko_search_base_url.rstrip("/")
    try:
        async with make_neko_search_client() as client:
            resp = await client.get(f"{base}/suggest", params={"q": q, "limit": limit})
            resp.raise_for_status()
            return resp.json()
    except Exception:
        logger.warning("neko-search suggest unavailable", exc_info=True)
        return None


async def _search_hashtags(db: AsyncSession, q: str, limit: int) -> list[dict]:
    """Search hashtags by name."""
    pattern = f"%{_escape_like(q.lower())}%"
    result = await db.execute(
        select(Hashtag)
        .where(Hashtag.name.ilike(pattern))
        .order_by(Hashtag.usage_count.desc())
        .limit(limit)
    )
    tags = result.scalars().all()

    return [
        {
            "name": tag.name,
            "url": f"{settings.server_url}/tags/{tag.name}",
            "history": [],
        }
        for tag in tags
    ]
