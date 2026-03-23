"""Remote nodeinfo fetching and software detection."""

import logging

import httpx

logger = logging.getLogger(__name__)

# Software names that support EmojiReact activity type
_EMOJI_REACT_SOFTWARE = {"pleroma", "akkoma", "fedibird", "nekonoverse"}

# Software names that support emoji reactions (EmojiReact or Like+_misskey_reaction)
_EMOJI_REACTION_SOFTWARE = _EMOJI_REACT_SOFTWARE | {"misskey", "calckey", "firefish", "sharkey"}

_CACHE_TTL = 86400  # 24 hours
_CACHE_TTL_FAIL = 3600  # 1 hour for failed fetches


async def get_domain_software(domain: str) -> str | None:
    """Get the software name of a remote instance via nodeinfo.

    Results are cached in Valkey for 24 hours.  Returns lowercase
    software name (e.g. "pleroma", "misskey") or None on failure.
    """
    name, _version, _instance_name = await get_domain_software_info(domain)
    return name


async def get_domain_software_info(
    domain: str,
) -> tuple[str | None, str | None, str | None]:
    """Get software name, version, and instance name of a remote instance.

    Results are cached in Valkey for 24 hours.
    Returns (lowercase_name, version, instance_name) or (None, None, None).
    """
    from app.valkey_client import valkey

    name_key = f"nodeinfo:software:{domain}"
    ver_key = f"nodeinfo:software_version:{domain}"
    iname_key = f"nodeinfo:instance_name:{domain}"

    cached_name = await valkey.get(name_key)
    if cached_name is not None:
        name_val = cached_name.decode() if isinstance(cached_name, bytes) else cached_name
        name = name_val if name_val != "" else None
        cached_ver = await valkey.get(ver_key)
        ver = None
        if cached_ver is not None:
            ver_val = cached_ver.decode() if isinstance(cached_ver, bytes) else cached_ver
            ver = ver_val if ver_val != "" else None
        cached_iname = await valkey.get(iname_key)
        iname = None
        if cached_iname is not None:
            iname_val = (
                cached_iname.decode()
                if isinstance(cached_iname, bytes)
                else cached_iname
            )
            iname = iname_val if iname_val != "" else None
        return name, ver, iname

    name, version, instance_name = await _fetch_software(domain)

    # Use shorter TTL for failed fetches so we retry sooner
    ttl = _CACHE_TTL if (name or instance_name) else _CACHE_TTL_FAIL
    await valkey.set(name_key, name or "", ex=ttl)
    await valkey.set(ver_key, version or "", ex=ttl)
    await valkey.set(iname_key, instance_name or "", ex=ttl)
    return name, version, instance_name


async def _fetch_software(
    domain: str,
) -> tuple[str | None, str | None, str | None]:
    """Fetch software name, version, and instance name from remote nodeinfo."""
    try:
        from app.utils.http_client import USER_AGENT
        from app.utils.network import is_safe_url
        async with httpx.AsyncClient(
            timeout=5, follow_redirects=False, verify=False,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            # Step 1: Discover nodeinfo URL
            wellknown_url = f"https://{domain}/.well-known/nodeinfo"
            if not is_safe_url(wellknown_url):
                return None, None, None
            resp = await client.get(wellknown_url)
            if resp.status_code != 200:
                return None, None, None
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
                return None, None, None

            # Validate nodeinfo URL before fetching
            if not is_safe_url(nodeinfo_url):
                return None, None, None

            # Step 2: Fetch nodeinfo
            resp = await client.get(nodeinfo_url)
            if resp.status_code != 200:
                return None, None, None
            info = resp.json()
            sw = info.get("software", {})
            name = sw.get("name", "")
            version = sw.get("version", "")
            metadata = info.get("metadata", {})
            instance_name = (
                metadata.get("nodeName")
                or metadata.get("name")
                or ""
            )

            # Fallback: fetch instance name from Mastodon-compatible API
            if not instance_name:
                instance_name = await _fetch_instance_name(client, domain)

            return (
                name.lower() if name else None,
                version if version else None,
                instance_name if instance_name else None,
            )
    except Exception:
        logger.debug("Failed to fetch nodeinfo for %s", domain, exc_info=True)
        return None, None, None


async def _fetch_instance_name(
    client: httpx.AsyncClient, domain: str
) -> str | None:
    """Fallback: fetch instance title from Mastodon-compatible instance API."""
    for path in ("/api/v2/instance", "/api/v1/instance"):
        try:
            resp = await client.get(f"https://{domain}{path}")
            if resp.status_code != 200:
                continue
            data = resp.json()
            title = data.get("title") or ""
            if title:
                return title
        except Exception:
            continue
    return None


async def uses_emoji_react(domain: str) -> bool:
    """Check if a remote domain supports EmojiReact activity type."""
    software = await get_domain_software(domain)
    return software in _EMOJI_REACT_SOFTWARE


async def supports_emoji_reactions(domain: str) -> bool:
    """Check if a remote domain supports any form of emoji reactions.

    Returns True for servers that understand EmojiReact or Like+_misskey_reaction.
    Returns False for Mastodon/GoToSocial/unknown (emoji reactions are meaningless there).
    """
    software = await get_domain_software(domain)
    return software in _EMOJI_REACTION_SOFTWARE


# Software known to ignore emoji reaction content (shows as plain ❤ like)
_EMOJI_REACTION_BLOCKLIST = {"mastodon"}


async def ignores_emoji_reactions(domain: str) -> bool:
    """Check if a remote domain is known to ignore emoji reaction content.

    Returns True for Mastodon (drops content, always shows ❤).
    Returns False for unknown servers (give them the benefit of the doubt).
    """
    software = await get_domain_software(domain)
    return software in _EMOJI_REACTION_BLOCKLIST
