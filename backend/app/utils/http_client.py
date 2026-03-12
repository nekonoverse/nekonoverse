"""Factory for httpx.AsyncClient with optional forward proxy support."""

import httpx

from app.config import settings


def get_proxy_url() -> str | None:
    """Return the proxy URL from settings, preferring https_proxy."""
    return settings.https_proxy or settings.http_proxy


def make_face_detect_client(**kwargs) -> httpx.AsyncClient:
    """Create an httpx.AsyncClient configured for the face-detect service.

    When ``settings.face_detect_uds`` is set, uses a Unix domain socket
    transport instead of TCP.
    """
    if settings.face_detect_uds:
        kwargs.setdefault(
            "transport", httpx.AsyncHTTPTransport(uds=settings.face_detect_uds)
        )
    kwargs.setdefault("timeout", 30.0)
    return httpx.AsyncClient(**kwargs)


def make_async_client(*, use_proxy: bool = True, **kwargs) -> httpx.AsyncClient:
    """Create an httpx.AsyncClient with proxy settings injected.

    Args:
        use_proxy: If True (default), inject proxy from settings.
                   Set to False for local/internal service calls.
        **kwargs: Additional arguments passed to httpx.AsyncClient.
    """
    if use_proxy and "proxy" not in kwargs:
        proxy_url = get_proxy_url()
        if proxy_url:
            kwargs["proxy"] = proxy_url
    return httpx.AsyncClient(**kwargs)
