"""httpx と AWS SigV4 を使用した S3 互換ストレージクライアント。"""

import hashlib
import hmac
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import httpx

from app.config import settings

# M-14: S3操作用の共有HTTPクライアント
_s3_client: httpx.AsyncClient | None = None


def _get_s3_client() -> httpx.AsyncClient:
    global _s3_client
    if _s3_client is None or _s3_client.is_closed:
        from app.utils.http_client import USER_AGENT
        _s3_client = httpx.AsyncClient(
            base_url=settings.s3_endpoint_url,
            timeout=30.0,
            headers={"User-Agent": USER_AGENT},
        )
    return _s3_client


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _signing_key(date_str: str) -> bytes:
    k = _sign(("AWS4" + settings.s3_secret_access_key).encode(), date_str)
    k = _sign(k, settings.s3_region)
    k = _sign(k, "s3")
    return _sign(k, "aws4_request")


def _endpoint_host() -> str:
    return urlparse(settings.s3_endpoint_url).netloc


def _auth_headers(
    method: str,
    path: str,
    content_sha256: str,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y%m%d")
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")

    headers = {
        "host": _endpoint_host(),
        "x-amz-date": amz_date,
        "x-amz-content-sha256": content_sha256,
    }
    if extra_headers:
        headers.update(extra_headers)

    signed_headers_list = sorted(headers.keys())
    signed_headers_str = ";".join(signed_headers_list)
    canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in signed_headers_list)

    canonical_request = "\n".join(
        [
            method,
            quote(path, safe="/"),
            "",
            canonical_headers,
            signed_headers_str,
            content_sha256,
        ]
    )

    credential_scope = f"{date_str}/{settings.s3_region}/s3/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )

    signature = hmac.new(
        _signing_key(date_str),
        string_to_sign.encode(),
        hashlib.sha256,
    ).hexdigest()

    headers["Authorization"] = (
        f"AWS4-HMAC-SHA256 "
        f"Credential={settings.s3_access_key_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers_str}, "
        f"Signature={signature}"
    )
    return headers


async def ensure_bucket() -> None:
    """バケットが存在しない場合に作成する。"""
    path = f"/{settings.s3_bucket}"
    content_sha256 = hashlib.sha256(b"").hexdigest()
    headers = _auth_headers("PUT", path, content_sha256)
    client = _get_s3_client()
    resp = await client.put(path, headers=headers)
    if resp.status_code not in (200, 409):
        resp.raise_for_status()


async def upload_file(key: str, data: bytes, content_type: str) -> str:
    """ファイルを S3 にアップロードする。ETag を返す。"""
    path = f"/{settings.s3_bucket}/{key}"
    content_sha256 = hashlib.sha256(data).hexdigest()
    extra = {"content-type": content_type}
    headers = _auth_headers("PUT", path, content_sha256, extra)
    headers["content-type"] = content_type
    client = _get_s3_client()
    resp = await client.put(path, content=data, headers=headers)
    resp.raise_for_status()
    return resp.headers.get("etag", "").strip('"')


async def delete_file(key: str) -> None:
    """S3 からファイルを削除する。"""
    path = f"/{settings.s3_bucket}/{key}"
    content_sha256 = hashlib.sha256(b"").hexdigest()
    headers = _auth_headers("DELETE", path, content_sha256)
    client = _get_s3_client()
    resp = await client.delete(path, headers=headers)
    if resp.status_code not in (200, 204, 404):
        resp.raise_for_status()


async def download_file(key: str) -> bytes:
    """S3 からファイルをダウンロードし、その内容を返す。"""
    path = f"/{settings.s3_bucket}/{key}"
    content_sha256 = "UNSIGNED-PAYLOAD"
    headers = _auth_headers("GET", path, content_sha256)
    client = _get_s3_client()
    resp = await client.get(path, headers=headers)
    resp.raise_for_status()
    return resp.content


async def get_file_stream(key: str) -> tuple[AsyncIterator[bytes], str, int]:
    """S3 からファイルをストリームとして取得する。(stream, content_type, size) を返す。"""
    path = f"/{settings.s3_bucket}/{key}"
    content_sha256 = "UNSIGNED-PAYLOAD"
    headers = _auth_headers("GET", path, content_sha256)
    client = _get_s3_client()
    resp = await client.send(
        client.build_request("GET", path, headers=headers),
        stream=True,
    )
    resp.raise_for_status()
    ct = resp.headers.get("content-type", "application/octet-stream")
    size = int(resp.headers.get("content-length", 0))

    async def _stream():
        try:
            async for chunk in resp.aiter_bytes():
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return _stream(), ct, size


def get_public_url(key: str) -> str:
    """指定された S3 キーの公開 URL を返す。"""
    return f"{settings.media_url}/{key}"


def generate_presigned_get_url(key: str, expires_in: int = 300) -> str:
    """S3 オブジェクトの GET 用 presigned URL を返す (AWS SigV4 query string 方式)。

    video-thumb の `/thumbnail_from_url` 等、内部マイクロサービスから一時的に
    S3 オブジェクトを取得させたい場面で使う。

    Args:
        key: S3 object key (bucket prefix なし)
        expires_in: 有効期限 (秒、1 〜 604800 = 7 日)

    Returns:
        presigned URL (`{s3_endpoint_url}/{bucket}/{key}?X-Amz-Algorithm=...`)

    Raises:
        ValueError: expires_in が AWS 仕様の範囲 (1-604800 秒) を超える場合
    """
    if not 1 <= expires_in <= 604800:
        raise ValueError(
            f"expires_in must be between 1 and 604800 seconds, got {expires_in}"
        )
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y%m%d")
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    credential_scope = f"{date_str}/{settings.s3_region}/s3/aws4_request"

    host = _endpoint_host()
    path = f"/{settings.s3_bucket}/{key}"
    canonical_uri = quote(path, safe="/")

    # 署名対象は host ヘッダのみ (presigned URL の慣習)
    signed_headers = "host"
    canonical_headers = f"host:{host}\n"

    # クエリ文字列 (キー名はソートする必要がある)
    query_params = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": f"{settings.s3_access_key_id}/{credential_scope}",
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(expires_in),
        "X-Amz-SignedHeaders": signed_headers,
    }
    canonical_query = "&".join(
        f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}"
        for k, v in sorted(query_params.items())
    )

    canonical_request = "\n".join(
        [
            "GET",
            canonical_uri,
            canonical_query,
            canonical_headers,
            signed_headers,
            "UNSIGNED-PAYLOAD",
        ]
    )
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )
    signature = hmac.new(
        _signing_key(date_str),
        string_to_sign.encode(),
        hashlib.sha256,
    ).hexdigest()

    return (
        f"{settings.s3_endpoint_url}{canonical_uri}"
        f"?{canonical_query}&X-Amz-Signature={signature}"
    )
