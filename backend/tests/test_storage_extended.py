"""Tests for storage module — S3-compatible storage with AWS SigV4."""

from unittest.mock import AsyncMock, MagicMock, patch

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
