import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.utils.media_proxy import verify_proxy_hmac

router = APIRouter(prefix="/api/v1/media", tags=["media_proxy"])

_MAX_SIZE = 20 * 1024 * 1024  # 20 MB
_ALLOWED_CONTENT_PREFIXES = ("image/", "video/", "audio/")
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def _is_private_host(hostname: str) -> bool:
    """Block requests to private/loopback IP ranges (SSRF protection)."""
    try:
        for info in socket.getaddrinfo(hostname, None):
            addr = ipaddress.ip_address(info[4][0])
            if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
                return True
    except (socket.gaierror, ValueError):
        return True  # can't resolve → block
    return False


@router.get("/proxy")
async def proxy_media(
    url: str = Query(..., min_length=1),
    h: str = Query(..., min_length=16, max_length=32),
):
    if not verify_proxy_hmac(url, h):
        raise HTTPException(status_code=403, detail="Invalid signature")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(status_code=403, detail="Invalid URL scheme")

    if _is_private_host(parsed.hostname):
        raise HTTPException(status_code=403, detail="Forbidden host")

    from app.utils.http_client import make_async_client

    async with make_async_client(
        timeout=_TIMEOUT, follow_redirects=False,
    ) as client:
        try:
            # リダイレクトを手動で追跡し、各ホップでSSRF検証を行う
            current_url = url
            resp = None
            for _ in range(3):
                resp = await client.get(current_url)
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("location")
                    if not location:
                        raise HTTPException(status_code=502, detail="Redirect without location")
                    # 相対URLを絶対URLに解決
                    resolved = urljoin(current_url, location)
                    redirect_parsed = urlparse(resolved)
                    if redirect_parsed.scheme not in ("http", "https") or not redirect_parsed.hostname:
                        raise HTTPException(status_code=403, detail="Invalid redirect URL")
                    if _is_private_host(redirect_parsed.hostname):
                        raise HTTPException(status_code=403, detail="Forbidden redirect host")
                    current_url = resolved
                else:
                    break
            else:
                raise HTTPException(status_code=502, detail="Too many redirects")
        except httpx.HTTPError:
            raise HTTPException(status_code=502, detail="Upstream fetch failed")

        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Upstream returned non-200")

        content_type = resp.headers.get("content-type", "")
        if not any(content_type.startswith(p) for p in _ALLOWED_CONTENT_PREFIXES):
            raise HTTPException(status_code=403, detail="Disallowed content type")

        body = resp.content
        if len(body) > _MAX_SIZE:
            raise HTTPException(status_code=413, detail="Response too large")

    return StreamingResponse(
        iter([body]),
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=86400",
            "Content-Length": str(len(body)),
        },
    )
