from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.config import settings
from app.dependencies import get_db
from app.services.actor_service import get_actor_by_username

router = APIRouter()


@router.get("/.well-known/webfinger")
async def webfinger(
    resource: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    if not resource.startswith("acct:"):
        raise HTTPException(status_code=400, detail="Invalid resource format")

    acct = resource[5:]  # Remove "acct:"
    if "@" not in acct:
        raise HTTPException(status_code=400, detail="Invalid acct format")

    username, domain = acct.split("@", 1)

    if domain != settings.domain:
        raise HTTPException(status_code=404, detail="User not found")

    actor = await get_actor_by_username(db, username, domain=None)
    if not actor:
        raise HTTPException(status_code=404, detail="User not found")

    actor_url = f"{settings.server_url}/users/{actor.username}"
    profile_url = f"{settings.server_url}/@{actor.username}"

    return Response(
        content='{"subject":"'
        + resource
        + '","aliases":["'
        + actor_url
        + '","'
        + profile_url
        + '"],"links":[{"rel":"self","type":"application/activity+json","href":"'
        + actor_url
        + '"},{"rel":"http://webfinger.net/rel/profile-page","type":"text/html","href":"'
        + profile_url
        + '"}]}',
        media_type="application/jrd+json",
    )
