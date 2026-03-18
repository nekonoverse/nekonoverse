"""Factory for httpx.AsyncClient with optional forward proxy support."""

import httpx

from app import __version__
from app.config import settings

USER_AGENT = f"Nekonoverse/{__version__}"


def get_proxy_url() -> str | None:
    """Return the proxy URL from settings, preferring https_proxy."""
    return settings.https_proxy or settings.http_proxy


def _inject_user_agent(kwargs: dict) -> None:
    """Ensure User-Agent header is present in kwargs."""
    headers = kwargs.get("headers")
    if headers is None:
        kwargs["headers"] = {"User-Agent": USER_AGENT}
    elif isinstance(headers, dict) and "User-Agent" not in headers:
        headers["User-Agent"] = USER_AGENT


def make_face_detect_client(**kwargs) -> httpx.AsyncClient:
    """Create an httpx.AsyncClient configured for the face-detect service.

    When ``settings.face_detect_uds`` is set, uses a Unix domain socket
    transport instead of TCP.

    Proxy is explicitly disabled by default to prevent httpx from using
    the ``HTTP_PROXY`` environment variable, since face-detect is typically
    an internal service.
    """
    _inject_user_agent(kwargs)
    if settings.face_detect_uds:
        kwargs.setdefault(
            "transport", httpx.AsyncHTTPTransport(uds=settings.face_detect_uds)
        )
    kwargs.setdefault("timeout", 30.0)
    kwargs.setdefault("proxy", None)
    return httpx.AsyncClient(**kwargs)


def make_media_transform_client(**kwargs) -> httpx.AsyncClient:
    """Create an httpx.AsyncClient for the media-proxy-transform service."""
    _inject_user_agent(kwargs)
    if settings.media_proxy_transform_uds:
        kwargs.setdefault(
            "transport", httpx.AsyncHTTPTransport(uds=settings.media_proxy_transform_uds)
        )
    kwargs.setdefault("timeout", 15.0)
    kwargs.setdefault("proxy", None)
    return httpx.AsyncClient(**kwargs)


def make_summary_proxy_client(**kwargs) -> httpx.AsyncClient:
    """Create an httpx.AsyncClient configured for the summary-proxy service."""
    _inject_user_agent(kwargs)
    if settings.summary_proxy_uds:
        kwargs.setdefault(
            "transport", httpx.AsyncHTTPTransport(uds=settings.summary_proxy_uds)
        )
    kwargs.setdefault("timeout", 15.0)
    kwargs.setdefault("proxy", None)
    return httpx.AsyncClient(**kwargs)


def make_async_client(*, use_proxy: bool = True, **kwargs) -> httpx.AsyncClient:
    """Create an httpx.AsyncClient with proxy settings injected.

    Args:
        use_proxy: If True (default), inject proxy from settings.
                   Set to False for local/internal service calls.
        **kwargs: Additional arguments passed to httpx.AsyncClient.
    """
    _inject_user_agent(kwargs)
    if use_proxy and "proxy" not in kwargs:
        proxy_url = get_proxy_url()
        if proxy_url:
            kwargs["proxy"] = proxy_url
    # When proxy is not wanted, explicitly set None to prevent httpx
    # from auto-detecting HTTP_PROXY environment variable.
    if not use_proxy:
        kwargs.setdefault("proxy", None)
    return httpx.AsyncClient(**kwargs)
