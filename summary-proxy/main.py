"""
Standalone URL summary/OGP extraction microservice.

Misskey summaly-compatible response format.
Accepts a URL, fetches the page, extracts OGP metadata, and returns a JSON summary.
"""

import hashlib
import ipaddress
import logging
import socket
import time
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query

logger = logging.getLogger("summary-proxy")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="summary-proxy")

# ---------------------------------------------------------------------------
# In-memory cache (TTL 1 hour, max 1000 entries)
# ---------------------------------------------------------------------------
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 3600  # 1 hour
_CACHE_MAX = 1000

_MAX_HTML_SIZE = 1 * 1024 * 1024  # 1 MB
_REQUEST_TIMEOUT = 10.0
_USER_AGENT = "NekonoverseSummaryBot/1.0 (+https://github.com/nekonoverse/nekonoverse)"


def _cache_get(url: str) -> dict | None:
    key = hashlib.sha256(url.encode()).hexdigest()
    entry = _CACHE.get(key)
    if entry is None:
        return None
    ts, data = entry
    if time.time() - ts > _CACHE_TTL:
        del _CACHE[key]
        return None
    return data


def _cache_set(url: str, data: dict) -> None:
    if len(_CACHE) >= _CACHE_MAX:
        # Evict oldest entries
        oldest = sorted(_CACHE.items(), key=lambda x: x[1][0])
        for k, _ in oldest[: len(oldest) // 4]:
            del _CACHE[k]
    key = hashlib.sha256(url.encode()).hexdigest()
    _CACHE[key] = (time.time(), data)


# ---------------------------------------------------------------------------
# SSRF protection
# ---------------------------------------------------------------------------
def _is_private_address(hostname: str) -> bool:
    """Check if hostname resolves to a private/reserved IP address."""
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for _, _, _, _, addr in infos:
            ip = ipaddress.ip_address(addr[0])
            if ip.is_private or ip.is_reserved or ip.is_loopback or ip.is_link_local:
                return True
    except (socket.gaierror, ValueError):
        return True  # Can't resolve = reject
    return False


# ---------------------------------------------------------------------------
# OGP extraction
# ---------------------------------------------------------------------------
def _extract_summary(html: str, url: str) -> dict:
    """Extract OGP metadata from HTML."""
    soup = BeautifulSoup(html, "lxml")

    def og(prop: str) -> str | None:
        tag = soup.find("meta", attrs={"property": f"og:{prop}"})
        if tag:
            return tag.get("content")
        return None

    def meta_name(name: str) -> str | None:
        tag = soup.find("meta", attrs={"name": name})
        if tag:
            return tag.get("content")
        return None

    title = og("title")
    if not title:
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else None

    description = og("description") or meta_name("description")

    thumbnail = og("image")
    if thumbnail:
        # Resolve relative URLs
        thumbnail = urljoin(url, thumbnail)

    icon = None
    # Try to find favicon
    link_icon = soup.find("link", rel=lambda r: r and "icon" in (r if isinstance(r, list) else [r]))
    if link_icon and link_icon.get("href"):
        icon = urljoin(url, link_icon["href"])

    site_name = og("site_name")

    return {
        "url": url,
        "title": title,
        "description": description,
        "thumbnail": thumbnail,
        "icon": icon,
        "siteName": site_name,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/summary")
async def get_summary(url: str = Query(..., min_length=1)):
    """Fetch URL and return OGP metadata summary (summaly-compatible)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return _empty_summary(url)

    if not parsed.hostname:
        return _empty_summary(url)

    # SSRF protection
    if _is_private_address(parsed.hostname):
        logger.warning("Blocked private address: %s", parsed.hostname)
        return _empty_summary(url)

    # Check cache
    cached = _cache_get(url)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(
            timeout=_REQUEST_TIMEOUT,
            follow_redirects=True,
            max_redirects=5,
        ) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml",
                },
            )

        if resp.status_code != 200:
            result = _empty_summary(url)
            _cache_set(url, result)
            return result

        content_type = resp.headers.get("content-type", "")
        if "text/html" not in content_type and "application/xhtml" not in content_type:
            result = _empty_summary(url)
            _cache_set(url, result)
            return result

        # Limit body size
        body = resp.content[:_MAX_HTML_SIZE]
        # Detect encoding
        charset = resp.charset_encoding or "utf-8"
        try:
            html = body.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            html = body.decode("utf-8", errors="replace")

        result = _extract_summary(html, str(resp.url))
        _cache_set(url, result)
        return result

    except (httpx.HTTPError, Exception) as e:
        logger.warning("Failed to fetch %s: %s", url, e)
        return _empty_summary(url)


def _empty_summary(url: str) -> dict:
    return {
        "url": url,
        "title": None,
        "description": None,
        "thumbnail": None,
        "icon": None,
        "siteName": None,
    }
