from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.config import settings
from app.dependencies import get_db
from app.models.actor import Actor
from app.models.note import Note

router = APIRouter()


@router.get("/.well-known/nodeinfo")
async def nodeinfo_discovery():
    return {
        "links": [
            {
                "rel": "http://nodeinfo.diaspora.software/ns/schema/2.0",
                "href": f"{settings.server_url}/nodeinfo/2.0",
            }
        ]
    }


@router.get("/nodeinfo/2.0")
async def nodeinfo(db: AsyncSession = Depends(get_db)):
    user_count_result = await db.execute(
        select(func.count()).select_from(Actor).where(Actor.domain.is_(None))
    )
    user_count = user_count_result.scalar() or 0

    post_count_result = await db.execute(
        select(func.count()).select_from(Note).where(Note.local.is_(True))
    )
    post_count = post_count_result.scalar() or 0

    # Active users: local actors who posted at least one note in the period
    now = datetime.now(timezone.utc)
    local_actor_ids = select(Actor.id).where(Actor.domain.is_(None))

    active_halfyear_result = await db.execute(
        select(func.count(func.distinct(Note.actor_id))).where(
            Note.local.is_(True),
            Note.actor_id.in_(local_actor_ids),
            Note.published >= now - timedelta(days=180),
            Note.deleted_at.is_(None),
        )
    )
    active_halfyear = active_halfyear_result.scalar() or 0

    active_month_result = await db.execute(
        select(func.count(func.distinct(Note.actor_id))).where(
            Note.local.is_(True),
            Note.actor_id.in_(local_actor_ids),
            Note.published >= now - timedelta(days=30),
            Note.deleted_at.is_(None),
        )
    )
    active_month = active_month_result.scalar() or 0

    # Registration status from server settings
    open_registrations = settings.registration_open
    try:
        from app.services.server_settings_service import get_setting
        mode = await get_setting(db, "registration_mode")
        if mode is not None:
            open_registrations = mode != "closed"
        else:
            reg = await get_setting(db, "registration_open")
            if reg is not None:
                open_registrations = reg == "true"
    except Exception:
        pass

    # Load server settings
    node_name = "Nekonoverse"
    node_description = "A cat-friendly ActivityPub server"
    node_icon_url = None
    node_theme_color = None
    try:
        from app.services.server_settings_service import get_setting
        name = await get_setting(db, "server_name")
        if name:
            node_name = name
        desc = await get_setting(db, "server_description")
        if desc:
            node_description = desc
        icon_url = await get_setting(db, "server_icon_url")
        if icon_url:
            node_icon_url = icon_url
        theme_color = await get_setting(db, "server_theme_color")
        if theme_color:
            node_theme_color = theme_color
    except Exception:
        pass

    metadata = {
        "nodeName": node_name,
        "nodeDescription": node_description,
        "features": ["emoji_reactions"],
    }
    if node_icon_url:
        metadata["iconUrl"] = node_icon_url
    if node_theme_color:
        metadata["themeColor"] = node_theme_color

    return {
        "version": "2.0",
        "software": {"name": "nekonoverse", "version": __version__},
        "protocols": ["activitypub"],
        "services": {"inbound": [], "outbound": []},
        "openRegistrations": open_registrations,
        "usage": {
            "users": {
                "total": user_count,
                "activeHalfyear": active_halfyear,
                "activeMonth": active_month,
            },
            "localPosts": post_count,
        },
        "metadata": metadata,
    }
