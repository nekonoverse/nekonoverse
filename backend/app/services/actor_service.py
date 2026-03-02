import json
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.actor import Actor

logger = logging.getLogger(__name__)

AP_ACCEPT = 'application/ld+json; profile="https://www.w3.org/ns/activitystreams"'
AP_CONTENT_TYPES = {"application/activity+json", "application/ld+json"}


async def get_actor_by_ap_id(db: AsyncSession, ap_id: str) -> Actor | None:
    result = await db.execute(select(Actor).where(Actor.ap_id == ap_id))
    return result.scalar_one_or_none()


async def get_actor_by_username(
    db: AsyncSession, username: str, domain: str | None = None
) -> Actor | None:
    result = await db.execute(
        select(Actor).where(Actor.username == username, Actor.domain == domain)
    )
    return result.scalar_one_or_none()


async def fetch_remote_actor(db: AsyncSession, ap_id: str) -> Actor | None:
    """Fetch a remote actor by AP ID, cache in DB."""
    # Check cache first
    existing = await get_actor_by_ap_id(db, ap_id)
    if existing and existing.last_fetched_at:
        age = (datetime.now(timezone.utc) - existing.last_fetched_at).total_seconds()
        if age < 3600:  # 1 hour cache
            return existing

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                ap_id,
                headers={"Accept": AP_ACCEPT},
                follow_redirects=True,
            )
            if resp.status_code != 200:
                logger.warning("Failed to fetch actor %s: HTTP %d", ap_id, resp.status_code)
                return existing

            data = resp.json()
    except Exception:
        logger.exception("Error fetching remote actor %s", ap_id)
        return existing

    return await upsert_remote_actor(db, data)


async def upsert_remote_actor(db: AsyncSession, data: dict) -> Actor | None:
    """Create or update a remote actor from JSON-LD data."""
    ap_id = data.get("id")
    if not ap_id:
        return None

    from urllib.parse import urlparse

    parsed = urlparse(ap_id)
    domain = parsed.hostname

    username = data.get("preferredUsername", "")
    if not username:
        return None

    public_key_pem = ""
    pk = data.get("publicKey")
    if isinstance(pk, dict):
        public_key_pem = pk.get("publicKeyPem", "")

    shared_inbox = None
    endpoints = data.get("endpoints")
    if isinstance(endpoints, dict):
        shared_inbox = endpoints.get("sharedInbox")

    existing = await get_actor_by_ap_id(db, ap_id)
    now = datetime.now(timezone.utc)

    if existing:
        existing.display_name = data.get("name", username)
        existing.summary = data.get("summary")
        existing.inbox_url = data.get("inbox", existing.inbox_url)
        existing.outbox_url = data.get("outbox", existing.outbox_url)
        existing.shared_inbox_url = shared_inbox or existing.shared_inbox_url
        existing.followers_url = data.get("followers")
        existing.following_url = data.get("following")
        existing.public_key_pem = public_key_pem or existing.public_key_pem
        existing.last_fetched_at = now
        icon = data.get("icon")
        if isinstance(icon, dict):
            existing.avatar_url = icon.get("url")
        image = data.get("image")
        if isinstance(image, dict):
            existing.header_url = image.get("url")
        existing.is_cat = data.get("isCat", False)
        await db.commit()
        await db.refresh(existing)
        return existing

    icon = data.get("icon")
    avatar_url = icon.get("url") if isinstance(icon, dict) else None
    image = data.get("image")
    header_url = image.get("url") if isinstance(image, dict) else None

    actor = Actor(
        ap_id=ap_id,
        type=data.get("type", "Person"),
        username=username,
        domain=domain,
        display_name=data.get("name", username),
        summary=data.get("summary"),
        avatar_url=avatar_url,
        header_url=header_url,
        inbox_url=data.get("inbox", ""),
        outbox_url=data.get("outbox"),
        shared_inbox_url=shared_inbox,
        followers_url=data.get("followers"),
        following_url=data.get("following"),
        public_key_pem=public_key_pem,
        is_cat=data.get("isCat", False),
        manually_approves_followers=data.get("manuallyApprovesFollowers", False),
        discoverable=data.get("discoverable", True),
        last_fetched_at=now,
    )
    db.add(actor)
    await db.commit()
    await db.refresh(actor)
    return actor


async def get_actor_public_key(db: AsyncSession, key_id: str) -> tuple[Actor | None, str]:
    """Get actor and public key from a key ID (e.g. https://example.com/users/alice#main-key)."""
    actor_ap_id = key_id.split("#")[0]
    actor = await fetch_remote_actor(db, actor_ap_id)
    if actor:
        return actor, actor.public_key_pem
    return None, ""
