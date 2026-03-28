from urllib.parse import urljoin, urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from app.utils.media_proxy import verify_proxy_hmac
from app.utils.network import is_private_host as _is_private_host

router = APIRouter(prefix="/api/v1/media", tags=["media_proxy"])

_MAX_SIZE = 20 * 1024 * 1024  # 20 MB
_ALLOWED_CONTENT_PREFIXES = ("image/", "video/", "audio/")
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# Content-Type が信頼できない場合の画像検出用マジックバイトシグネチャ
_IMAGE_SIGNATURES: list[tuple[bytes, str]] = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),   # PNG / APNG
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),  # RIFF....WEBP (check WEBP at offset 8)
    (b"BM", "image/bmp"),
    (b"II\x2a\x00", "image/tiff"),
    (b"MM\x00\x2a", "image/tiff"),
    (b"\xff\x0a", "image/jxl"),             # JPEG XL codestream
    (b"\x00\x00\x00\x0c\x4a\x58\x4c\x20", "image/jxl"),  # JPEG XL container
]


def _detect_image_type(head: bytes) -> str | None:
    """マジックバイトから画像の MIME タイプを検出する。不明な場合は None を返す。"""
    for sig, mime in _IMAGE_SIGNATURES:
        if head[:len(sig)] == sig:
            if sig == b"RIFF" and head[8:12] != b"WEBP":
                continue
            return mime
    # AVIF/HEIF: オフセット4の ftyp ボックス
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"avif", b"avis", b"mif1", b"heic", b"heix"):
            return "image/avif"
    return None


async def _transform_image(body: bytes, **params) -> tuple[bytes, str]:
    """画像を外部変換サービスに送信する。エラー時は元画像にフォールバックする。"""
    from app.config import settings
    from app.utils.http_client import make_media_transform_client

    form_data = {k: str(v) for k, v in params.items() if v}
    try:
        async with make_media_transform_client() as client:
            base = settings.media_proxy_transform_base_url
            resp = await client.post(
                f"{base}/transform" if not base.endswith("/transform") else base,
                files={"file": ("image", body)},
                data=form_data,
            )
            if resp.status_code == 200:
                return resp.content, resp.headers.get("content-type", "image/webp")
    except Exception:
        pass
    return body, "image/webp"


@router.get("/proxy")
async def proxy_media(
    url: str = Query(..., min_length=1),
    h: str = Query(..., min_length=16, max_length=32),
    avatar: int | None = Query(None),
    emoji: int | None = Query(None),
    preview: int | None = Query(None),
    static: int | None = Query(None),
    badge: int | None = Query(None),
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
        body = resp.content

        if not any(content_type.startswith(p) for p in _ALLOWED_CONTENT_PREFIXES):
            # application/octet-stream 等の場合、先頭バイトで画像判定
            detected = _detect_image_type(body[:12]) if body else None
            if detected:
                content_type = detected
            else:
                raise HTTPException(status_code=403, detail="Disallowed content type")
        if len(body) > _MAX_SIZE:
            raise HTTPException(status_code=413, detail="Response too large")

    # パラメータが指定されており、画像コンテンツかつサービスが設定済みの場合に変換
    from app.config import settings

    needs_transform = any([avatar, emoji, preview, static, badge])
    if needs_transform and content_type.startswith("image/") and settings.media_proxy_transform_enabled:
        body, content_type = await _transform_image(
            body, avatar=avatar, emoji=emoji, preview=preview,
            static=static, badge=badge,
        )

    return Response(
        content=body,
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=86400",
            "Content-Length": str(len(body)),
        },
    )
