"""Remote nodeinfo fetching and software detection."""

import logging

import httpx

logger = logging.getLogger(__name__)

# Software names that support EmojiReact activity type
_EMOJI_REACT_SOFTWARE = {"pleroma", "akkoma", "fedibird"}

_CACHE_TTL = 86400  # 24 hours


async def get_domain_software(domain: str) -> str | None:
    """Get the software name of a remote instance via nodeinfo.

    Results are cached in Valkey for 24 hours.  Returns lowercase
    software name (e.g. "pleroma", "misskey") or None on failure.
    """
    from app.valkey_client import valkey

    cache_key = f"nodeinfo:software:{domain}"
    cached = await valkey.get(cache_key)
    if cached is not None:
        return cached.decode() if cached != b"" else None

    software = await _fetch_software(domain)

    # Cache result (empty string for None so we don't re-fetch failures)
    await valkey.set(cache_key, software or "", ex=_CACHE_TTL)
    return software


async def _fetch_software(domain: str) -> str | None:
    """Fetch software name from remote nodeinfo."""
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
            # Step 1: Discover nodeinfo URL
            resp = await client.get(f"https://{domain}/.well-known/nodeinfo")
            if resp.status_code != 200:
                return None
            data = resp.json()
            links = data.get("links", [])

            nodeinfo_url = None
            for link in links:
                href = link.get("href", "")
                rel = link.get("rel", "")
                if "nodeinfo" in rel and href:
                    nodeinfo_url = href
                    break
            if not nodeinfo_url:
                return None

            # Step 2: Fetch nodeinfo
            resp = await client.get(nodeinfo_url)
            if resp.status_code != 200:
                return None
            info = resp.json()
            name = info.get("software", {}).get("name", "")
            return name.lower() if name else None
    except Exception:
        logger.debug("Failed to fetch nodeinfo for %s", domain, exc_info=True)
        return None


async def uses_emoji_react(domain: str) -> bool:
    """Check if a remote domain supports EmojiReact activity type."""
    software = await get_domain_software(domain)
    return software in _EMOJI_REACT_SOFTWARE
