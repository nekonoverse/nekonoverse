"""Tests for SSRF protection across outbound request paths."""

import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.utils.network import is_private_host, is_safe_url


# --- Unit tests for shared SSRF utility ---


def test_is_private_host_loopback():
    assert is_private_host("127.0.0.1") is True


def test_is_private_host_link_local():
    assert is_private_host("169.254.169.254") is True


def test_is_private_host_unresolvable():
    assert is_private_host("nonexistent.invalid.test") is True


def test_is_safe_url_rejects_private():
    with patch("app.utils.network.is_private_host", return_value=True):
        assert is_safe_url("http://internal-host/secret") is False


def test_is_safe_url_rejects_bad_scheme():
    assert is_safe_url("file:///etc/passwd") is False
    assert is_safe_url("javascript:alert(1)") is False
    assert is_safe_url("ftp://files.example.com/data") is False


def test_is_safe_url_allows_https():
    with patch("app.utils.network.is_private_host", return_value=False):
        assert is_safe_url("https://remote.example.com/actor") is True


# --- actor_service._signed_get blocks private hosts ---


async def test_signed_get_blocks_private_url(db):
    from app.services.actor_service import _signed_get

    with patch("app.utils.network.is_safe_url", return_value=False):
        result = await _signed_get(db, "http://169.254.169.254/metadata")
    assert result is None


async def test_signed_get_allows_public_url(db):
    from app.services.actor_service import _signed_get

    fake_resp = httpx.Response(200, json={"type": "Person"})
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=fake_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.utils.network.is_safe_url", return_value=True),
        patch("app.utils.http_client.httpx.AsyncClient", return_value=mock_client),
    ):
        result = await _signed_get(db, "https://remote.example.com/users/alice")
    assert result is not None
    assert result.status_code == 200


# --- resolve_webfinger blocks private domains ---


async def test_resolve_webfinger_blocks_private_domain(db):
    from app.services.actor_service import resolve_webfinger

    with patch("app.utils.network.is_private_host", return_value=True):
        result = await resolve_webfinger(db, "alice", "192.168.1.1")
    assert result is None


# --- emoji_service blocks private URLs ---


async def test_import_remote_emoji_blocks_private_url(db):
    """import_remote_emoji_to_local rejects URLs pointing to private hosts."""
    from app.models.custom_emoji import CustomEmoji
    from app.services.emoji_service import import_remote_emoji_to_local

    remote_emoji = CustomEmoji(
        id=uuid.uuid4(),
        shortcode="test_private",
        domain="evil.example",
        url="http://192.168.1.100/evil.png",
    )
    db.add(remote_emoji)
    await db.flush()

    with pytest.raises(ValueError, match="private or invalid"):
        with patch("app.utils.network.is_safe_url", return_value=False):
            await import_remote_emoji_to_local(db, remote_emoji.id)


# --- focal_point_service._download_image blocks redirect SSRF ---


async def test_focal_download_blocks_redirect_to_private():
    """_download_image blocks redirects to private hosts."""
    from app.services.focal_point_service import _download_image

    redirect_resp = httpx.Response(
        302, headers={"location": "http://169.254.169.254/metadata"},
    )

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=redirect_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    def is_priv(h):
        return h == "169.254.169.254"

    with (
        patch("app.utils.network.is_private_host", side_effect=is_priv),
        patch("app.utils.http_client.httpx.AsyncClient", return_value=mock_client),
    ):
        result = await _download_image("https://cdn.example.com/image.jpg")
    assert result is None


async def test_focal_download_follows_safe_redirect():
    """_download_image follows redirects to safe hosts."""
    from app.services.focal_point_service import _download_image

    redirect_resp = httpx.Response(
        302, headers={"location": "https://cdn2.example.com/real.jpg"},
    )
    final_resp = httpx.Response(
        200, content=b"\x89PNG" + b"\x00" * 50,
        headers={"content-type": "image/png"},
    )

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[redirect_resp, final_resp])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.utils.network.is_private_host", return_value=False),
        patch("app.utils.http_client.httpx.AsyncClient", return_value=mock_client),
    ):
        result = await _download_image("https://cdn.example.com/image.jpg")
    assert result is not None
    assert result == b"\x89PNG" + b"\x00" * 50
