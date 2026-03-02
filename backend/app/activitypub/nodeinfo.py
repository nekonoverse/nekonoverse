from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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

    return {
        "version": "2.0",
        "software": {"name": "nekonoverse", "version": "0.1.0"},
        "protocols": ["activitypub"],
        "services": {"inbound": [], "outbound": []},
        "openRegistrations": True,
        "usage": {
            "users": {
                "total": user_count,
                "activeHalfyear": user_count,
                "activeMonth": user_count,
            },
            "localPosts": post_count,
        },
        "metadata": {
            "nodeName": "Nekonoverse",
            "nodeDescription": "A cat-friendly ActivityPub server",
            "features": ["emoji_reactions"],
        },
    }
