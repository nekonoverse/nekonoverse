import hashlib
import hmac as _hmac
from urllib.parse import quote

from app.config import settings


def _media_proxy_signing_key() -> bytes:
    """メディアプロキシの HMAC 署名に使用する鍵を返す。"""
    key = settings.media_proxy_key or settings.derive_key("media-proxy")
    return key.encode()


def media_proxy_url(
    original_url: str | None,
    *,
    variant: str | None = None,
    static: bool = False,
) -> str:
    """リモート URL を HMAC 署名付きプロキシ URL に変換する。

    ローカル URL (/ または server_url で始まるもの) はそのまま返す。

    variant: Misskey 互換プリセット ("avatar", "emoji", "preview", "badge")。
    static: True の場合、アニメーション画像の最初のフレームを抽出する。
    """
    if not original_url:
        return ""
    if original_url.startswith("/") or original_url.startswith(settings.server_url):
        return original_url
    h = _hmac.new(
        _media_proxy_signing_key(), original_url.encode(), hashlib.sha256,
    ).hexdigest()[:32]
    url = f"{settings.server_url}/api/v1/media/proxy?url={quote(original_url, safe='')}&h={h}"
    if variant:
        url += f"&{variant}=1"
    if static:
        url += "&static=1"
    return url


def verify_proxy_hmac(url: str, h: str) -> bool:
    """HMAC が指定された URL と一致するか検証する。

    L-7: レガシー16文字HMAC互換とレガシーキー互換を廃止。
    32文字のHMAC署名のみ受け入れる。
    """
    key = _media_proxy_signing_key()
    expected = _hmac.new(key, url.encode(), hashlib.sha256).hexdigest()[:32]
    return _hmac.compare_digest(expected, h)
