from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import VERSION as __version__
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
    from sqlalchemy import case

    from app.services.server_settings_service import get_settings_batch

    # 統計クエリ: user_count + post_count を1クエリ、active_halfyear + active_month を1クエリ
    user_count_result = await db.execute(
        select(func.count()).select_from(Actor).where(Actor.domain.is_(None))
    )
    user_count = user_count_result.scalar() or 0

    post_count_result = await db.execute(
        select(func.count()).select_from(Note).where(Note.local.is_(True))
    )
    post_count = post_count_result.scalar() or 0

    # アクティブユーザー: halfyear と month を1クエリで取得
    now = datetime.now(timezone.utc)
    local_actor_ids = select(Actor.id).where(Actor.domain.is_(None))
    halfyear_ago = now - timedelta(days=180)
    month_ago = now - timedelta(days=30)

    active_result = await db.execute(
        select(
            func.count(func.distinct(Note.actor_id)).label("halfyear"),
            func.count(
                func.distinct(case((Note.published >= month_ago, Note.actor_id)))
            ).label("month"),
        ).where(
            Note.local.is_(True),
            Note.actor_id.in_(local_actor_ids),
            Note.published >= halfyear_ago,
            Note.deleted_at.is_(None),
        )
    )
    row = active_result.one()
    active_halfyear = row.halfyear or 0
    active_month = row.month or 0

    # サーバー設定を一括取得（Valkey mget → DB 1クエリ）
    setting_keys = [
        "registration_mode", "registration_open",
        "server_name", "server_description",
        "server_icon_url", "server_theme_color",
        "katex_enabled",
    ]
    node_name = "Nekonoverse"
    node_description = "A cat-friendly ActivityPub server"
    node_icon_url = None
    node_theme_color = None
    open_registrations = settings.registration_open
    features = ["emoji_reactions"]
    try:
        s = await get_settings_batch(db, setting_keys)
        mode = s.get("registration_mode")
        if mode is not None:
            open_registrations = mode != "closed"
        else:
            reg = s.get("registration_open")
            if reg is not None:
                open_registrations = reg == "true"
        if s.get("server_name"):
            node_name = s["server_name"]
        if s.get("server_description"):
            node_description = s["server_description"]
        node_icon_url = s.get("server_icon_url") or None
        node_theme_color = s.get("server_theme_color") or None
        if s.get("katex_enabled") == "true":
            features.append("katex")
    except Exception:
        pass

    metadata = {
        "nodeName": node_name,
        "nodeDescription": node_description,
        "features": features,
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
