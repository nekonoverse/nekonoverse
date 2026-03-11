import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.actor import Actor

logger = logging.getLogger(__name__)


def actor_uri(actor: Actor) -> str:
    """Return the canonical ActivityPub URI for an actor.

    For local actors, derives from settings.server_url to ensure correct
    scheme.  For remote actors, returns the stored ap_id.
    """
    if actor.domain is None:
        return f"{settings.server_url}/users/{actor.username}"
    return actor.ap_id


AP_ACCEPT = 'application/ld+json; profile="https://www.w3.org/ns/activitystreams"'
AP_CONTENT_TYPES = {"application/activity+json", "application/ld+json"}


async def get_actor_by_ap_id(db: AsyncSession, ap_id: str) -> Actor | None:
    result = await db.execute(select(Actor).where(Actor.ap_id == ap_id))
    actor = result.scalar_one_or_none()
    if actor:
        return actor

    # Fallback: if ap_id looks like a local actor URL, try lookup by username.
    # This handles http/https scheme mismatch in stored ap_id.
    from urllib.parse import urlparse

    parsed = urlparse(ap_id)
    if parsed.hostname == settings.domain and parsed.path.startswith("/users/"):
        username = parsed.path.split("/users/", 1)[1].rstrip("/")
        if username:
            return await get_actor_by_username(db, username, domain=None)

    return None


async def get_actor_by_username(
    db: AsyncSession,
    username: str,
    domain: str | None = None,
) -> Actor | None:
    lookup = username.lower() if domain is None else username
    result = await db.execute(select(Actor).where(Actor.username == lookup, Actor.domain == domain))
    return result.scalar_one_or_none()


# 署名鍵キャッシュ (server_url変更がない限り不変)
_signing_key_cache: tuple[str, str] | None | bool = False


async def _get_signing_key(db: AsyncSession) -> tuple[str, str] | None:
    """Get a local actor's key_id and private_key_pem for signed fetches."""
    global _signing_key_cache
    if _signing_key_cache is not False:
        return _signing_key_cache  # type: ignore[return-value]

    from app.models.user import User

    result = await db.execute(select(User).options(selectinload(User.actor)).limit(1))
    user = result.scalar_one_or_none()
    if not user or not user.actor:
        _signing_key_cache = None
        return None
    # Use dynamic URL for local actor to ensure correct scheme
    actor_url = f"{settings.server_url}/users/{user.actor.username}"
    key_id = f"{actor_url}#main-key"
    _signing_key_cache = (key_id, user.private_key_pem)
    return _signing_key_cache


async def _signed_get(db: AsyncSession, url: str) -> httpx.Response | None:
    """Perform a signed HTTP GET (Authorized Fetch / Secure Mode)."""
    from app.activitypub.http_signature import sign_request

    signing = await _get_signing_key(db)
    headers = {"Accept": AP_ACCEPT}

    if signing:
        key_id, private_key_pem = signing
        sig_headers = sign_request(
            private_key_pem=private_key_pem,
            key_id=key_id,
            method="GET",
            url=url,
            body=None,
        )
        headers.update(sig_headers)

    from app.config import settings
    from app.utils.http_client import make_async_client

    async with make_async_client(
        timeout=10.0, verify=not settings.skip_ssl_verify,
    ) as client:
        return await client.get(url, headers=headers, follow_redirects=True)


async def fetch_remote_actor(db: AsyncSession, ap_id: str) -> Actor | None:
    """Fetch a remote actor by AP ID, cache in DB."""
    # Check cache first
    existing = await get_actor_by_ap_id(db, ap_id)
    if existing and existing.last_fetched_at:
        age = (datetime.now(timezone.utc) - existing.last_fetched_at).total_seconds()
        if age < 3600:  # 1 hour cache
            return existing

    try:
        resp = await _signed_get(db, ap_id)
        if not resp or resp.status_code != 200:
            logger.warning(
                "Failed to fetch actor %s: HTTP %s",
                ap_id,
                resp.status_code if resp else "no response",
            )
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

    # Parse profile fields from PropertyValue attachments
    from app.utils.sanitize import sanitize_html

    attachments = data.get("attachment", [])
    fields = None
    if isinstance(attachments, list):
        fields = [
            {
                "name": sanitize_html(att.get("name", "")),
                "value": sanitize_html(att.get("value", "")),
            }
            for att in attachments
            if isinstance(att, dict) and att.get("type") == "PropertyValue"
        ]

    # Parse birthday from vcard:bday
    parsed_birthday = None
    bday = data.get("vcard:bday")
    if bday:
        from datetime import date

        try:
            parsed_birthday = date.fromisoformat(bday)
        except (ValueError, TypeError):
            pass

    # Detect bot from actor type
    actor_type = data.get("type", "Person")
    is_bot = actor_type == "Service"

    # Extract custom emoji from tags
    tags = data.get("tag", [])
    if isinstance(tags, dict):
        tags = [tags]
    for tag in tags:
        if isinstance(tag, dict) and tag.get("type") == "Emoji":
            icon = tag.get("icon", {})
            emoji_url = icon.get("url") if isinstance(icon, dict) else None
            emoji_name = tag.get("name", "").strip(":")
            if emoji_name and emoji_url and domain:
                from app.services.emoji_service import upsert_remote_emoji

                static_url = icon.get("staticUrl") if isinstance(icon, dict) else None
                _ml = tag.get("_misskey_license")
                license_text = tag.get("license") or (
                    _ml.get("freeText") if isinstance(_ml, dict) else None
                )
                await upsert_remote_emoji(
                    db,
                    shortcode=emoji_name,
                    domain=domain,
                    url=emoji_url,
                    static_url=static_url,
                    aliases=tag.get("keywords"),
                    license=license_text,
                    is_sensitive=bool(tag.get("isSensitive", False)),
                    author=tag.get("author") or tag.get("creator"),
                    description=tag.get("description"),
                    copy_permission=tag.get("copyPermission"),
                    usage_info=tag.get("usageInfo"),
                    is_based_on=tag.get("isBasedOn"),
                    category=tag.get("category"),
                )

    if existing:
        existing.type = actor_type
        existing.display_name = data.get("name", username)
        raw_summary = data.get("summary")
        existing.summary = sanitize_html(raw_summary) if raw_summary else None
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
        existing.is_bot = is_bot
        existing.require_signin_to_view = bool(
            data.get("_misskey_requireSigninToViewContents", False)
        )
        existing.make_notes_followers_only_before = data.get(
            "_misskey_makeNotesFollowersOnlyBefore"
        )
        existing.make_notes_hidden_before = data.get("_misskey_makeNotesHiddenBefore")
        existing.manually_approves_followers = data.get(
            "manuallyApprovesFollowers",
            existing.manually_approves_followers,
        )
        existing.discoverable = data.get("discoverable", existing.discoverable)
        if fields is not None:
            existing.fields = fields
        existing.birthday = parsed_birthday
        existing.featured_url = data.get("featured")
        existing.moved_to_ap_id = data.get("movedTo")
        aka = data.get("alsoKnownAs")
        if isinstance(aka, list):
            existing.also_known_as = aka
        await db.commit()
        await db.refresh(existing)
        return existing

    icon = data.get("icon")
    avatar_url = icon.get("url") if isinstance(icon, dict) else None
    image = data.get("image")
    header_url = image.get("url") if isinstance(image, dict) else None

    aka = data.get("alsoKnownAs")
    also_known_as = aka if isinstance(aka, list) else None

    actor = Actor(
        ap_id=ap_id,
        type=actor_type,
        username=username,
        domain=domain,
        display_name=data.get("name", username),
        summary=sanitize_html(data["summary"]) if data.get("summary") else None,
        avatar_url=avatar_url,
        header_url=header_url,
        inbox_url=data.get("inbox", ""),
        outbox_url=data.get("outbox"),
        shared_inbox_url=shared_inbox,
        followers_url=data.get("followers"),
        following_url=data.get("following"),
        public_key_pem=public_key_pem,
        is_cat=data.get("isCat", False),
        is_bot=is_bot,
        require_signin_to_view=bool(data.get("_misskey_requireSigninToViewContents", False)),
        make_notes_followers_only_before=data.get("_misskey_makeNotesFollowersOnlyBefore"),
        make_notes_hidden_before=data.get("_misskey_makeNotesHiddenBefore"),
        manually_approves_followers=data.get("manuallyApprovesFollowers", False),
        discoverable=data.get("discoverable", True),
        fields=fields or [],
        birthday=parsed_birthday,
        last_fetched_at=now,
        featured_url=data.get("featured"),
        moved_to_ap_id=data.get("movedTo"),
        also_known_as=also_known_as,
    )
    db.add(actor)
    await db.commit()
    await db.refresh(actor)
    return actor


async def resolve_webfinger(db: AsyncSession, username: str, domain: str) -> Actor | None:
    """Resolve a remote actor via WebFinger, then fetch their AP profile."""
    # Check if we already have this actor cached
    existing = await get_actor_by_username(db, username, domain)
    if existing:
        return existing

    webfinger_url = f"https://{domain}/.well-known/webfinger?resource=acct:{username}@{domain}"
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=not settings.skip_ssl_verify) as client:
            resp = await client.get(webfinger_url, follow_redirects=True)
        if resp.status_code != 200:
            logger.warning(
                "WebFinger failed for %s@%s: HTTP %s",
                username,
                domain,
                resp.status_code,
            )
            return None

        data = resp.json()
    except Exception:
        logger.exception("Error resolving WebFinger for %s@%s", username, domain)
        return None

    # Find the self link with AP content type
    links = data.get("links", [])
    ap_id = None
    for link in links:
        rel = link.get("rel", "")
        link_type = link.get("type", "")
        if rel == "self" and link_type in AP_CONTENT_TYPES:
            ap_id = link.get("href")
            break

    if not ap_id:
        # Try application/activity+json explicitly
        for link in links:
            if link.get("rel") == "self" and "activity+json" in link.get("type", ""):
                ap_id = link.get("href")
                break

    if not ap_id:
        logger.warning("No AP self link in WebFinger for %s@%s", username, domain)
        return None

    return await fetch_remote_actor(db, ap_id)


async def get_actor_public_key(db: AsyncSession, key_id: str) -> tuple[Actor | None, str]:
    """Get actor and public key from a key ID (e.g. https://example.com/users/alice#main-key)."""
    actor_ap_id = key_id.split("#")[0]
    actor = await fetch_remote_actor(db, actor_ap_id)
    if actor:
        return actor, actor.public_key_pem
    return None, ""
