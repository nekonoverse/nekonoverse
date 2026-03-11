import hashlib
import hmac as _hmac
from urllib.parse import quote

from app.config import settings


def _media_proxy_signing_key() -> bytes:
    """Return the key used for media proxy HMAC signing."""
    key = settings.media_proxy_key or settings.derive_key("media-proxy")
    return key.encode()


def media_proxy_url(original_url: str | None) -> str:
    """Convert a remote URL to an HMAC-signed proxy URL.

    Local URLs (starting with / or server_url) are returned as-is.
    """
    if not original_url:
        return ""
    if original_url.startswith("/") or original_url.startswith(settings.server_url):
        return original_url
    h = _hmac.new(
        _media_proxy_signing_key(), original_url.encode(), hashlib.sha256,
    ).hexdigest()[:32]
    return f"/api/v1/media/proxy?url={quote(original_url, safe='')}&h={h}"


def verify_proxy_hmac(url: str, h: str) -> bool:
    """Verify that the HMAC matches the given URL."""
    key = _media_proxy_signing_key()
    expected = _hmac.new(key, url.encode(), hashlib.sha256).hexdigest()[:32]

    # 旧形式(16文字)との互換性を維持
    if len(h) == 16:
        if _hmac.compare_digest(expected[:16], h):
            return True

    if _hmac.compare_digest(expected, h):
        return True

    # レガシーキー(secret_key直接使用)との互換性
    legacy = _hmac.new(
        settings.secret_key.encode(), url.encode(), hashlib.sha256,
    ).hexdigest()[:32]
    if len(h) == 16:
        return _hmac.compare_digest(legacy[:16], h)
    return _hmac.compare_digest(legacy, h)
