from unittest.mock import patch

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
    assert "/api/v1/media/proxy?url=" in result
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


def _proxy_params(url: str) -> dict:
    """Generate valid proxy query params for the given URL."""
    from urllib.parse import parse_qs
    from urllib.parse import urlparse as _urlparse
    proxy = media_proxy_url(url)
    parsed = _urlparse(proxy)
    params = parse_qs(parsed.query)
    return {"url": params["url"][0], "h": params["h"][0]}


def _upstream(responses):
    """上流サーバーのレスポンスを順に返すモッククライアントに差し替える。

    responses は httpx.Response のリスト、またはリクエストを受け取る関数。
    戻り値の patch オブジェクトの .requests に受けたリクエストが記録される。
    """
    requests: list[httpx.Request] = []
    queue = list(responses) if isinstance(responses, list) else None

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return queue.pop(0) if queue is not None else responses(request)

    p = patch(
        "app.utils.http_client.make_async_client",
        side_effect=lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    p.requests = requests
    return p


async def test_proxy_valid_hmac(app_client, mock_valkey):
    """Valid HMAC should proxy the remote content."""
    url = "https://remote.example/image.png"
    fake_response = httpx.Response(
        200,
        content=b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
        headers={"content-type": "image/png"},
    )
    upstream = _upstream([fake_response])

    with (
        upstream as factory,
        patch("app.api.mastodon.media_proxy._is_private_host", return_value=False),
    ):
        resp = await app_client.get("/api/v1/media/proxy", params=_proxy_params(url))
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert "cache-control" in resp.headers
    assert resp.content == b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    assert "sandbox" in resp.headers["content-security-policy"]
    assert resp.headers["x-content-type-options"] == "nosniff"
    # 上流への接続は接続先 IP を検証するクライアントで行う
    assert factory.call_args.kwargs["ssrf_guard"] is True


async def test_proxy_blocks_non_media_content_type(app_client, mock_valkey):
    """Should reject responses with non-media Content-Type."""
    url = "https://remote.example/page.html"
    fake_response = httpx.Response(
        200,
        content=b"<html></html>",
        headers={"content-type": "text/html"},
    )

    with (
        _upstream([fake_response]),
        patch("app.api.mastodon.media_proxy._is_private_host", return_value=False),
    ):
        resp = await app_client.get("/api/v1/media/proxy", params=_proxy_params(url))
    assert resp.status_code == 403


async def test_proxy_redirect_follows_and_checks_ssrf(app_client, mock_valkey):
    """Redirect to a valid host should be followed and return the final content."""
    url = "https://cdn.example/image.png"

    redirect_resp = httpx.Response(
        302, headers={"location": "https://cdn2.example/real.png"},
    )
    final_resp = httpx.Response(
        200, content=b"\x89PNG" + b"\x00" * 50, headers={"content-type": "image/png"},
    )

    with (
        _upstream([redirect_resp, final_resp]),
        patch("app.api.mastodon.media_proxy._is_private_host", return_value=False),
    ):
        resp = await app_client.get("/api/v1/media/proxy", params=_proxy_params(url))
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"


async def test_proxy_redirect_to_private_blocked(app_client, mock_valkey):
    """Redirect to a private IP should be blocked."""
    url = "https://cdn.example/image.png"

    redirect_resp = httpx.Response(
        302, headers={"location": "http://169.254.169.254/metadata"},
    )
    upstream = _upstream([redirect_resp])

    def is_private(hostname):
        return hostname in ("169.254.169.254",)

    with (
        upstream,
        patch("app.api.mastodon.media_proxy._is_private_host", side_effect=is_private),
    ):
        resp = await app_client.get("/api/v1/media/proxy", params=_proxy_params(url))
    assert resp.status_code == 403
    assert [str(r.url) for r in upstream.requests] == [url]


async def test_proxy_relative_redirect(app_client, mock_valkey):
    """Relative Location header should be resolved against the current URL."""
    url = "https://cdn.example/old.png"

    redirect_resp = httpx.Response(302, headers={"location": "/new/image.png"})
    final_resp = httpx.Response(
        200, content=b"\x89PNG" + b"\x00" * 50, headers={"content-type": "image/png"},
    )
    upstream = _upstream([redirect_resp, final_resp])

    with (
        upstream,
        patch("app.api.mastodon.media_proxy._is_private_host", return_value=False),
    ):
        resp = await app_client.get("/api/v1/media/proxy", params=_proxy_params(url))
    assert resp.status_code == 200
    # 2回目のGETは絶対URLに解決されたURLで呼ばれる
    assert str(upstream.requests[1].url) == "https://cdn.example/new/image.png"


async def test_proxy_too_many_redirects(app_client, mock_valkey):
    """More than 3 redirects should return 502."""
    url = "https://cdn.example/loop.png"

    def loop(request):
        return httpx.Response(302, headers={"location": "https://cdn.example/loop.png"})

    with (
        _upstream(loop),
        patch("app.api.mastodon.media_proxy._is_private_host", return_value=False),
    ):
        resp = await app_client.get("/api/v1/media/proxy", params=_proxy_params(url))
    assert resp.status_code == 502


async def test_proxy_rejects_oversized_declared_length(app_client, mock_valkey):
    """Content-Length が上限を超える場合は本文を読まずに 413。"""
    from app.api.mastodon import media_proxy

    class _NeverRead(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError("body must not be read")
            yield b""  # pragma: no cover

    def handler(request):
        return httpx.Response(
            200,
            headers={
                "content-type": "image/png",
                "content-length": str(media_proxy._MAX_SIZE + 1),
            },
            stream=_NeverRead(),
        )

    with (
        _upstream(handler),
        patch("app.api.mastodon.media_proxy._is_private_host", return_value=False),
    ):
        resp = await app_client.get(
            "/api/v1/media/proxy", params=_proxy_params("https://big.example/a.png")
        )
    assert resp.status_code == 413


async def test_proxy_stops_reading_when_stream_exceeds_limit(app_client, mock_valkey):
    """Content-Length なしで上限を超えて送られてきたら途中で打ち切って 413。"""
    chunks_sent = 0

    class _Endless(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal chunks_sent
            while True:
                chunks_sent += 1
                yield b"\x00" * 1024

    def handler(request):
        return httpx.Response(200, headers={"content-type": "image/png"}, stream=_Endless())

    with (
        _upstream(handler),
        patch("app.api.mastodon.media_proxy._is_private_host", return_value=False),
        patch("app.api.mastodon.media_proxy._MAX_SIZE", 10 * 1024),
    ):
        resp = await app_client.get(
            "/api/v1/media/proxy", params=_proxy_params("https://big.example/b.png")
        )
    assert resp.status_code == 413
    assert chunks_sent == 11


async def test_proxy_total_timeout(app_client, mock_valkey):
    """少しずつ送り続ける上流は全体の制限時間で打ち切る。"""
    import asyncio

    class _Slow(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                await asyncio.sleep(0.05)
                yield b"\x00"

    def handler(request):
        return httpx.Response(200, headers={"content-type": "image/png"}, stream=_Slow())

    with (
        _upstream(handler),
        patch("app.api.mastodon.media_proxy._is_private_host", return_value=False),
        patch("app.api.mastodon.media_proxy._TOTAL_TIMEOUT", 0.3),
    ):
        resp = await app_client.get(
            "/api/v1/media/proxy", params=_proxy_params("https://slow.example/c.png")
        )
    assert resp.status_code == 504


async def test_attachment_url_proxied(authed_client, db, mock_valkey):
    """Remote attachment URLs in API response should be proxied."""
    from app.models.note_attachment import NoteAttachment
    from tests.conftest import make_note, make_remote_actor

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
    assert "/api/v1/media/proxy?url=" in media_url
    assert "media.example" in media_url


async def test_proxy_svg_served_sandboxed(app_client, mock_valkey):
    """SVG は表示用に中継するが、直接開いてもスクリプトが動かないよう sandbox 付きで返す。"""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    with (
        _upstream([httpx.Response(200, content=svg, headers={"content-type": "image/svg+xml"})]),
        patch("app.api.mastodon.media_proxy._is_private_host", return_value=False),
    ):
        resp = await app_client.get(
            "/api/v1/media/proxy", params=_proxy_params("https://remote.example/a.svg")
        )
    assert resp.status_code == 200
    csp = resp.headers["content-security-policy"]
    assert "sandbox" in csp
    assert "default-src 'none'" in csp
    assert "script-src" not in csp
