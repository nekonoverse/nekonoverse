"""Mastodon-compatible stub/lightweight endpoints for client compatibility.

Endpoints here are required by Mastodon clients but either return
minimal/empty responses or are lightweight wrappers around existing logic.
"""

import re
import uuid

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

    import hashlib

    token_str = auth_header[7:]
    token_hash = hashlib.sha256(token_str.encode()).hexdigest()
    result = await db.execute(
        select(OAuthToken).where(OAuthToken.access_token == token_hash)
    )
    token = result.scalar_one_or_none()
    if not token:
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


_VALID_THEME_COLOR_KEYS = {
    "bg-primary", "bg-secondary", "bg-card",
    "text-primary", "text-secondary",
    "accent", "accent-hover", "accent-text",
    "border", "reblog", "favourite",
}
_VALID_BASE_THEMES = {"dark", "light", "novel"}
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _prefs_response(prefs: dict) -> dict:
    return {
        "posting:default:visibility": "public",
        "posting:default:sensitive": False,
        "posting:default:language": None,
        "reading:expand:media": "default",
        "reading:expand:spoilers": False,
        "posting:source_media_type": prefs.get("source_media_type", "auto"),
        "theme_customization": prefs.get("theme_customization", None),
    }


@router.get("/api/v1/preferences")
async def get_preferences(
    user: User = Depends(get_current_user),
):
    """Return user preferences."""
    return _prefs_response(user.preferences or {})


@router.patch("/api/v1/preferences")
async def update_preferences(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update user preferences."""
    from fastapi import HTTPException

    body = await request.json()
    prefs = dict(user.preferences or {})

    _VALID_SOURCE_MEDIA_TYPES = {"auto", "mfm", "plain"}
    smt = body.get("posting:source_media_type")
    if smt is not None:
        if smt not in _VALID_SOURCE_MEDIA_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid source_media_type: must be one of {_VALID_SOURCE_MEDIA_TYPES}",
            )
        prefs["source_media_type"] = smt

    tc = body.get("theme_customization")
    if tc is not None:
        if tc is False or tc == {}:
            prefs.pop("theme_customization", None)
        elif isinstance(tc, dict):
            base = tc.get("base")
            if base not in _VALID_BASE_THEMES:
                raise HTTPException(422, "Invalid base theme")
            colors = tc.get("colors")
            if not isinstance(colors, dict):
                raise HTTPException(422, "colors must be an object")
            if set(colors.keys()) != _VALID_THEME_COLOR_KEYS:
                raise HTTPException(
                    422,
                    f"colors must contain exactly: {sorted(_VALID_THEME_COLOR_KEYS)}",
                )
            for k, v in colors.items():
                if not isinstance(v, str) or not _HEX_COLOR_RE.match(v):
                    raise HTTPException(422, f"Invalid color for {k}: must be #rrggbb hex")
            name = tc.get("name")
            if name is not None and (not isinstance(name, str) or len(name) > 50):
                raise HTTPException(422, "name must be a string of at most 50 chars")
            prefs["theme_customization"] = {
                "base": base,
                "colors": colors,
                **({"name": name} if name else {}),
            }
        else:
            raise HTTPException(422, "theme_customization must be an object or false")

    user.preferences = prefs
    await db.commit()

    return _prefs_response(prefs)


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
async def list_announcements(
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """List active server announcements (Mastodon-compatible)."""
    from app.api.mastodon.statuses import _to_mastodon_datetime
    from app.services.announcement_service import get_dismissed_ids, list_active_announcements

    announcements = await list_active_announcements(db)
    dismissed: set[uuid.UUID] = set()
    if user:
        dismissed = await get_dismissed_ids(db, user.id)

    return [
        {
            "id": str(a.id),
            "content": a.content_html,
            "starts_at": _to_mastodon_datetime(a.starts_at) if a.starts_at else None,
            "ends_at": _to_mastodon_datetime(a.ends_at) if a.ends_at else None,
            "all_day": a.all_day,
            "published_at": _to_mastodon_datetime(a.created_at),
            "updated_at": _to_mastodon_datetime(a.updated_at),
            "read": a.id in dismissed,
            "mentions": [],
            "statuses": [],
            "tags": [],
            "emojis": [],
            "reactions": [],
        }
        for a in announcements
    ]


@router.post("/api/v1/announcements/{announcement_id}/dismiss", status_code=204)
async def dismiss_announcement(
    announcement_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark an announcement as read (Mastodon-compatible)."""
    from app.services.announcement_service import dismiss_announcement as _dismiss

    await _dismiss(db, announcement_id, user.id)
    await db.commit()


@router.get("/api/v1/announcements/unread_count")
async def announcements_unread_count(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get unread announcement count."""
    from app.services.announcement_service import get_unread_count

    count = await get_unread_count(db, user.id)
    return {"count": count}


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
