"""Tests for storage module — S3-compatible storage with AWS SigV4."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(autouse=True)
def _reset_s3_client():
    """Reset the global S3 client before each test to prevent stale connections."""
    import app.storage
    app.storage._s3_client = None
    yield
    app.storage._s3_client = None

# ── get_public_url ───────────────────────────────────────────────────────


def test_get_public_url():
    from app.storage import get_public_url

    url = get_public_url("avatars/abc.png")
    assert url.endswith("/avatars/abc.png")


# ── ensure_bucket ────────────────────────────────────────────────────────


async def test_ensure_bucket_creates():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_client = AsyncMock()
    mock_client.put = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.storage.httpx.AsyncClient", return_value=mock_client):
        from app.storage import ensure_bucket

        await ensure_bucket()
    mock_client.put.assert_called_once()


async def test_ensure_bucket_already_exists():
    mock_response = MagicMock()
    mock_response.status_code = 409  # Conflict = already exists
    mock_client = AsyncMock()
    mock_client.put = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.storage.httpx.AsyncClient", return_value=mock_client):
        from app.storage import ensure_bucket

        await ensure_bucket()  # Should not raise


# ── upload_file ──────────────────────────────────────────────────────────


async def test_upload_file_returns_etag():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {"etag": '"abc123"'}
    mock_client = AsyncMock()
    mock_client.put = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.storage.httpx.AsyncClient", return_value=mock_client):
        from app.storage import upload_file

        etag = await upload_file("test.png", b"fake-data", "image/png")
    assert etag == "abc123"


# ── delete_file ──────────────────────────────────────────────────────────


async def test_delete_file_success():
    mock_response = MagicMock()
    mock_response.status_code = 204
    mock_client = AsyncMock()
    mock_client.delete = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.storage.httpx.AsyncClient", return_value=mock_client):
        from app.storage import delete_file

        await delete_file("test.png")  # Should not raise


async def test_delete_file_not_found_ok():
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_client = AsyncMock()
    mock_client.delete = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.storage.httpx.AsyncClient", return_value=mock_client):
        from app.storage import delete_file

        await delete_file("nonexistent.png")  # Should not raise


# ── _signing_key / _auth_headers ─────────────────────────────────────────


def test_auth_headers_contain_authorization():
    import hashlib

    from app.storage import _auth_headers

    content_sha = hashlib.sha256(b"").hexdigest()
    headers = _auth_headers("GET", "/test-bucket/key", content_sha)
    assert "Authorization" in headers
    assert "AWS4-HMAC-SHA256" in headers["Authorization"]
    assert "x-amz-date" in headers


# ── generate_presigned_get_url ───────────────────────────────────────────


def test_generate_presigned_get_url_format():
    """presigned URL に必要なクエリパラメータが含まれる。"""
    from app.storage import generate_presigned_get_url

    url = generate_presigned_get_url("u/abc/test.mp4", expires_in=300)

    # endpoint + bucket + key
    assert url.startswith("http://nekono3s:8080/nekonoverse/u/abc/test.mp4?")
    # AWS SigV4 query parameters
    assert "X-Amz-Algorithm=AWS4-HMAC-SHA256" in url
    assert "X-Amz-Credential=" in url
    assert "X-Amz-Date=" in url
    assert "X-Amz-Expires=300" in url
    assert "X-Amz-SignedHeaders=host" in url
    assert "X-Amz-Signature=" in url


def test_generate_presigned_get_url_distinct_signatures_for_different_keys():
    """異なる key は異なる署名になる。"""
    from app.storage import generate_presigned_get_url

    url1 = generate_presigned_get_url("a.mp4", expires_in=300)
    url2 = generate_presigned_get_url("b.mp4", expires_in=300)

    sig1 = url1.split("X-Amz-Signature=")[1]
    sig2 = url2.split("X-Amz-Signature=")[1]
    assert sig1 != sig2


def test_generate_presigned_get_url_url_safe_encoding():
    """key に / や . を含んでも URL エンコードが壊れない。"""
    from app.storage import generate_presigned_get_url

    url = generate_presigned_get_url("path/to/file.with.dots.mp4", expires_in=60)
    assert "/path/to/file.with.dots.mp4?" in url


def test_generate_presigned_get_url_rejects_invalid_expires_in():
    """expires_in は AWS 仕様 (1-604800 秒) の範囲外で ValueError。"""
    from app.storage import generate_presigned_get_url

    with pytest.raises(ValueError):
        generate_presigned_get_url("k", expires_in=0)
    with pytest.raises(ValueError):
        generate_presigned_get_url("k", expires_in=-1)
    with pytest.raises(ValueError):
        generate_presigned_get_url("k", expires_in=604801)


def test_generate_presigned_get_url_strips_trailing_slash():
    """endpoint URL に末尾スラッシュがあっても `//bucket/key` にならない。"""
    import app.storage
    from app.storage import generate_presigned_get_url

    # settings.s3_endpoint_url を一時的に末尾スラッシュ付きに
    orig = app.storage.settings.s3_endpoint_url
    try:
        app.storage.settings.s3_endpoint_url = "http://nekono3s:8080/"
        url = generate_presigned_get_url("test.mp4", expires_in=60)
        assert url.startswith("http://nekono3s:8080/nekonoverse/test.mp4?")
        assert "//nekonoverse" not in url
    finally:
        app.storage.settings.s3_endpoint_url = orig


def test_generate_presigned_get_url_signature_matches_botocore():
    """自前実装の署名が botocore (AWS 公式 SDK) の S3SigV4QueryAuth と一致する。

    自前 SigV4 実装が AWS 仕様に追従していることを担保する回帰テスト (#1016)。
    タイムスタンプ依存を排除するため、自前実装が生成した URL から X-Amz-Date を
    抽出して botocore に同じ時刻で再署名させ、署名値を含む全クエリパラメータの
    バイト一致を確認する。署名アルゴリズム (canonical_request 構築 → string_to_sign →
    HMAC) のいずれかが破綻すると確実に落ちる。
    """
    from urllib.parse import parse_qs, urlparse

    from botocore.auth import S3SigV4QueryAuth
    from botocore.awsrequest import AWSRequest
    from botocore.credentials import Credentials

    from app.config import settings
    from app.storage import generate_presigned_get_url

    # 自前実装で URL を生成
    key = "u/abc/test.mp4"
    our_url = generate_presigned_get_url(key, expires_in=300)
    our_qs = parse_qs(urlparse(our_url).query)

    # 自前実装の X-Amz-Date を botocore の timestamp として注入
    creds = Credentials(
        access_key=settings.s3_access_key_id,
        secret_key=settings.s3_secret_access_key,
    )
    auth = S3SigV4QueryAuth(
        credentials=creds,
        service_name="s3",
        region_name=settings.s3_region,
        expires=300,
    )
    # 自前実装の rstrip("/") 経路と path 構造を揃える (endpoint の末尾スラッシュ正規化)
    endpoint = settings.s3_endpoint_url.rstrip("/")
    request = AWSRequest(
        method="GET",
        url=f"{endpoint}/{settings.s3_bucket}/{key}",
    )
    request.context["timestamp"] = our_qs["X-Amz-Date"][0]
    auth.add_auth(request)
    ref_qs = parse_qs(urlparse(request.url).query)

    # 全パラメータが完全一致 (署名アルゴリズム破綻時に確実に落ちる)
    for param in (
        "X-Amz-Algorithm",
        "X-Amz-Credential",
        "X-Amz-Date",
        "X-Amz-Expires",
        "X-Amz-SignedHeaders",
        "X-Amz-Signature",
    ):
        assert our_qs[param] == ref_qs[param], (
            f"{param} mismatch: ours={our_qs[param]!r} botocore={ref_qs[param]!r}"
        )
