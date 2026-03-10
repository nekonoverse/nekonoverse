import hashlib
import hmac as _hmac
from urllib.parse import quote

from app.config import settings


def media_proxy_url(original_url: str | None) -> str:
    """Convert a remote URL to an HMAC-signed proxy URL.

    Local URLs (starting with / or server_url) are returned as-is.
    """
    if not original_url:
        return ""
    if original_url.startswith("/") or original_url.startswith(settings.server_url):
        return original_url
    h = _hmac.new(settings.secret_key.encode(), original_url.encode(), hashlib.sha256).hexdigest()[
        :32
    ]
    return f"/api/v1/media/proxy?url={quote(original_url, safe='')}&h={h}"


def verify_proxy_hmac(url: str, h: str) -> bool:
    """Verify that the HMAC matches the given URL."""
    expected = _hmac.new(settings.secret_key.encode(), url.encode(), hashlib.sha256).hexdigest()[
        :32
    ]
    # 旧形式(16文字)との互換性を維持
    if len(h) == 16:
        return _hmac.compare_digest(expected[:16], h)
    return _hmac.compare_digest(expected, h)
