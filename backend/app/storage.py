"""S3-compatible storage client using httpx and AWS SigV4."""

import hashlib
import hmac
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import httpx

from app.config import settings


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
    method: str, path: str, content_sha256: str,
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

    canonical_request = "\n".join([
        method, quote(path, safe="/"), "",
        canonical_headers, signed_headers_str, content_sha256,
    ])

    credential_scope = f"{date_str}/{settings.s3_region}/s3/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amz_date, credential_scope,
        hashlib.sha256(canonical_request.encode()).hexdigest(),
    ])

    signature = hmac.new(
        _signing_key(date_str), string_to_sign.encode(), hashlib.sha256,
    ).hexdigest()

    headers["Authorization"] = (
        f"AWS4-HMAC-SHA256 "
        f"Credential={settings.s3_access_key_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers_str}, "
        f"Signature={signature}"
    )
    return headers


async def ensure_bucket() -> None:
    """Create the bucket if it doesn't exist."""
    path = f"/{settings.s3_bucket}"
    content_sha256 = hashlib.sha256(b"").hexdigest()
    headers = _auth_headers("PUT", path, content_sha256)
    async with httpx.AsyncClient(base_url=settings.s3_endpoint_url) as client:
        resp = await client.put(path, headers=headers)
        if resp.status_code not in (200, 409):
            resp.raise_for_status()


async def upload_file(key: str, data: bytes, content_type: str) -> str:
    """Upload a file to S3. Returns the ETag."""
    path = f"/{settings.s3_bucket}/{key}"
    content_sha256 = hashlib.sha256(data).hexdigest()
    extra = {"content-type": content_type}
    headers = _auth_headers("PUT", path, content_sha256, extra)
    headers["content-type"] = content_type
    async with httpx.AsyncClient(base_url=settings.s3_endpoint_url) as client:
        resp = await client.put(path, content=data, headers=headers)
        resp.raise_for_status()
    return resp.headers.get("etag", "").strip('"')


async def delete_file(key: str) -> None:
    """Delete a file from S3."""
    path = f"/{settings.s3_bucket}/{key}"
    content_sha256 = hashlib.sha256(b"").hexdigest()
    headers = _auth_headers("DELETE", path, content_sha256)
    async with httpx.AsyncClient(base_url=settings.s3_endpoint_url) as client:
        resp = await client.delete(path, headers=headers)
        if resp.status_code not in (200, 204, 404):
            resp.raise_for_status()


async def get_file_stream(key: str) -> tuple[AsyncIterator[bytes], str, int]:
    """Get a file from S3 as a stream. Returns (stream, content_type, size)."""
    path = f"/{settings.s3_bucket}/{key}"
    content_sha256 = "UNSIGNED-PAYLOAD"
    headers = _auth_headers("GET", path, content_sha256)
    client = httpx.AsyncClient(base_url=settings.s3_endpoint_url)
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
    """Return the public URL for a given S3 key."""
    return f"{settings.media_url}/{key}"
