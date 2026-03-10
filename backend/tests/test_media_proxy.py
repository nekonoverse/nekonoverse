from unittest.mock import AsyncMock, patch

import httpx

from app.utils.media_proxy import media_proxy_url, verify_proxy_hmac


# --- Unit tests for helper ---


def test_proxy_url_local_passthrough():
    """Local URLs (starting with /) should be returned as-is."""
    assert media_proxy_url("/default-avatar.svg") == "/default-avatar.svg"


def test_proxy_url_server_url_passthrough():
    """URLs starting with server_url should be returned as-is."""
    from app.config import settings

    local = f"{settings.server_url}/media/file.jpg"
    assert media_proxy_url(local) == local


def test_proxy_url_empty():
    assert media_proxy_url(None) == ""
    assert media_proxy_url("") == ""


def test_proxy_url_remote_signed():
    """Remote URLs should be rewritten to proxy URL with HMAC."""
    result = media_proxy_url("https://remote.example/img.png")
    assert result.startswith("/api/v1/media/proxy?url=")
    assert "&h=" in result
    # Extract h param
    h = result.split("&h=")[1]
    assert len(h) == 32


def test_verify_hmac_valid():
    url = "https://remote.example/img.png"
    proxy = media_proxy_url(url)
    h = proxy.split("&h=")[1]
    assert verify_proxy_hmac(url, h) is True


def test_verify_hmac_invalid():
    assert verify_proxy_hmac("https://remote.example/img.png", "0000000000000000") is False


# --- API endpoint tests ---


async def test_proxy_invalid_hmac(app_client, mock_valkey):
    resp = await app_client.get(
        "/api/v1/media/proxy",
        params={"url": "https://evil.example/img.png", "h": "0000000000000000"},
    )
    assert resp.status_code == 403


async def test_proxy_missing_params(app_client, mock_valkey):
    resp = await app_client.get("/api/v1/media/proxy")
    assert resp.status_code == 422


async def test_proxy_valid_hmac(app_client, mock_valkey):
    """Valid HMAC should proxy the remote content."""
    url = "https://remote.example/image.png"
    proxy = media_proxy_url(url)
    # Extract query params
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(proxy)
    params = parse_qs(parsed.query)

    fake_response = httpx.Response(
        200,
        content=b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
        headers={"content-type": "image/png"},
    )

    with (
        patch("app.api.mastodon.media_proxy.httpx.AsyncClient") as MockClient,
        patch("app.api.mastodon.media_proxy._is_private_host", return_value=False),
    ):
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=fake_response)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        resp = await app_client.get(
            "/api/v1/media/proxy",
            params={"url": params["url"][0], "h": params["h"][0]},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert "cache-control" in resp.headers


async def test_proxy_blocks_non_media_content_type(app_client, mock_valkey):
    """Should reject responses with non-media Content-Type."""
    url = "https://remote.example/page.html"
    proxy = media_proxy_url(url)
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(proxy)
    params = parse_qs(parsed.query)

    fake_response = httpx.Response(
        200,
        content=b"<html></html>",
        headers={"content-type": "text/html"},
    )

    with (
        patch("app.api.mastodon.media_proxy.httpx.AsyncClient") as MockClient,
        patch("app.api.mastodon.media_proxy._is_private_host", return_value=False),
    ):
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=fake_response)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        resp = await app_client.get(
            "/api/v1/media/proxy",
            params={"url": params["url"][0], "h": params["h"][0]},
        )
        assert resp.status_code == 403


async def test_attachment_url_proxied(authed_client, db, mock_valkey):
    """Remote attachment URLs in API response should be proxied."""
    from tests.conftest import make_remote_actor, make_note
    from app.models.note_attachment import NoteAttachment

    remote = await make_remote_actor(db, username="media_test", domain="media.example")
    note = await make_note(db, remote, content="With media", local=False)

    att = NoteAttachment(
        note_id=note.id,
        position=0,
        remote_url="https://media.example/files/photo.jpg",
        remote_mime_type="image/jpeg",
    )
    db.add(att)
    await db.flush()

    resp = await authed_client.get(f"/api/v1/statuses/{note.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["media_attachments"]) == 1
    media_url = data["media_attachments"][0]["url"]
    assert media_url.startswith("/api/v1/media/proxy?url=")
    assert "media.example" in media_url
