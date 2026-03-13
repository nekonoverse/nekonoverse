"""Mastodon-compatible stub/lightweight endpoints for client compatibility.

Endpoints here are required by Mastodon clients but either return
minimal/empty responses or are lightweight wrappers around existing logic.
"""


from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, get_optional_user
from app.models.user import User

router = APIRouter(tags=["mastodon-compat"])


# --- GET /api/v1/apps/verify_credentials ---


@router.get("/api/v1/apps/verify_credentials")
async def verify_app_credentials(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Verify the OAuth application token. Returns app info."""
    from app.models.oauth import OAuthApplication, OAuthToken

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Unauthorized")

    token_str = auth_header[7:]
    result = await db.execute(
        select(OAuthToken).where(OAuthToken.access_token == token_str)
    )
    token = result.scalar_one_or_none()
    if not token or token.revoked_at or token.is_expired:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(
        select(OAuthApplication).where(OAuthApplication.id == token.application_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Application not found")

    return {
        "id": str(app.id),
        "name": app.name,
        "website": app.website,
        "scopes": (app.scopes or "read").split(),
        "redirect_uri": app.redirect_uris,
    }


# --- GET /api/v1/preferences ---


@router.get("/api/v1/preferences")
async def get_preferences(
    user: User = Depends(get_current_user),
):
    """Return user preferences (defaults for now)."""
    return {
        "posting:default:visibility": "public",
        "posting:default:sensitive": False,
        "posting:default:language": None,
        "reading:expand:media": "default",
        "reading:expand:spoilers": False,
    }


# --- GET /api/v1/favourites ---


@router.get("/api/v1/favourites")
async def list_favourites(
    limit: int = Query(default=20, ge=1, le=40),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List statuses the current user has favourited (⭐ reacted)."""
    from app.api.mastodon.statuses import notes_to_responses
    from app.models.note import Note
    from app.models.reaction import Reaction
    from app.services.note_service import _note_load_options, get_reaction_summaries

    result = await db.execute(
        select(Reaction.note_id)
        .where(Reaction.actor_id == user.actor_id, Reaction.emoji == "\u2b50")
        .order_by(Reaction.created_at.desc())
        .limit(limit)
    )
    note_ids = [row[0] for row in result.all()]
    if not note_ids:
        return []

    notes_result = await db.execute(
        select(Note)
        .options(*_note_load_options())
        .where(Note.id.in_(note_ids), Note.deleted_at.is_(None))
    )
    notes_map = {n.id: n for n in notes_result.scalars().all()}
    # ID順序を維持
    notes = [notes_map[nid] for nid in note_ids if nid in notes_map]

    reactions_map = await get_reaction_summaries(db, [n.id for n in notes], user.actor_id)
    return await notes_to_responses(notes, reactions_map, db, actor_id=user.actor_id)


# --- Stub endpoints (return empty arrays for client compatibility) ---


@router.get("/api/v1/filters")
async def list_filters_v1(user: User = Depends(get_current_user)):
    """List content filters (stub - returns empty array)."""
    return []


@router.get("/api/v2/filters")
async def list_filters_v2(user: User = Depends(get_current_user)):
    """List content filters v2 (stub - returns empty array)."""
    return []


@router.get("/api/v1/announcements")
async def list_announcements(user: User | None = Depends(get_optional_user)):
    """List server announcements (stub - returns empty array)."""
    return []


@router.get("/api/v1/followed_tags")
async def list_followed_tags(user: User = Depends(get_current_user)):
    """List followed hashtags (stub - returns empty array)."""
    return []


@router.get("/api/v1/conversations")
async def list_conversations(user: User = Depends(get_current_user)):
    """List DM conversations (stub - returns empty array)."""
    return []


@router.get("/api/v1/lists")
async def list_lists(user: User = Depends(get_current_user)):
    """List custom lists (stub - returns empty array)."""
    return []


@router.get("/api/v1/markers")
async def get_markers(
    timeline: list[str] = Query(default=[], alias="timeline[]"),
    user: User = Depends(get_current_user),
):
    """Get timeline position markers (stub - returns empty object)."""
    return {}


@router.post("/api/v1/markers")
async def update_markers(
    user: User = Depends(get_current_user),
):
    """Update timeline position markers (stub - returns empty object)."""
    return {}
