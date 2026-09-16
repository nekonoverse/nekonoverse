"""外部リクエストの SSRF 保護 (リダイレクト再検証・接続先 IP 検証) の回帰テスト。"""

import asyncio
import ipaddress
import socket
from unittest.mock import patch

import httpx
import pytest

from app.utils.http_client import make_async_client
from app.utils.network import UnsafeURLError, _is_blocked_ip, safe_get


@pytest.fixture
def private_networks_blocked():
    with patch("app.config.settings.allow_private_networks", False):
        yield


def _public_dns(ip: str = "93.184.216.34"):
    return patch(
        "app.utils.network.socket.getaddrinfo",
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))],
    )


# ── IP 判定 ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "addr",
    ["::ffff:127.0.0.1", "::ffff:169.254.169.254", "0.0.0.0", "::", "224.0.0.1", "fd00::1"],
)
def test_blocked_ip_variants(addr):
    assert _is_blocked_ip(ipaddress.ip_address(addr)) is True


def test_public_ip_not_blocked():
    assert _is_blocked_ip(ipaddress.ip_address("93.184.216.34")) is False


# ── safe_get ─────────────────────────────────────────────────────────────


def _mock_client(handler) -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(wrapped)), seen


async def test_safe_get_blocks_redirect_to_private(private_networks_blocked):
    def handler(request):
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})

    client, seen = _mock_client(handler)

    def resolve(host, *_args, **_kwargs):
        ip = "169.254.169.254" if host == "169.254.169.254" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    with patch("app.utils.network.socket.getaddrinfo", side_effect=resolve):
        with pytest.raises(UnsafeURLError):
            await safe_get(client, "https://attacker.example/actor")
    # 内部アドレスへのリクエストは送られていない
    assert [str(r.url) for r in seen] == ["https://attacker.example/actor"]


async def test_safe_get_blocks_initial_private_url(private_networks_blocked):
    client, seen = _mock_client(lambda r: httpx.Response(200))
    with pytest.raises(UnsafeURLError):
        await safe_get(client, "http://127.0.0.1:8080/")
    assert seen == []


async def test_safe_get_follows_relative_redirect_and_resigns(private_networks_blocked):
    def handler(request):
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "https://b.example/new"})
        return httpx.Response(200, json={"ok": True})

    client, seen = _mock_client(handler)
    signed_for: list[str] = []

    def headers_for(url: str) -> dict[str, str]:
        signed_for.append(url)
        return {"X-Signed-For": url}

    with _public_dns():
        resp = await safe_get(client, "https://a.example/old", headers_for=headers_for)
    assert resp.status_code == 200
    assert signed_for == ["https://a.example/old", "https://b.example/new"]
    assert [r.headers["x-signed-for"] for r in seen] == signed_for


async def test_safe_get_too_many_redirects(private_networks_blocked):
    client, _ = _mock_client(
        lambda r: httpx.Response(302, headers={"location": "https://loop.example/"})
    )
    with _public_dns(), pytest.raises(httpx.TooManyRedirects):
        await safe_get(client, "https://loop.example/", max_redirects=2)


async def test_signed_get_does_not_follow_redirect_to_private(db, private_networks_blocked):
    from app.services import actor_service

    client, seen = _mock_client(
        lambda r: httpx.Response(302, headers={"location": "http://10.0.0.5/admin"})
    )

    def resolve(host, *_args, **_kwargs):
        ip = "10.0.0.5" if host == "10.0.0.5" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    with (
        patch("app.utils.network.socket.getaddrinfo", side_effect=resolve),
        patch.object(actor_service, "_get_shared_http_client", return_value=client),
    ):
        result = await actor_service._signed_get(db, "https://remote.example/users/x")
    assert result is None
    assert len(seen) == 1


# ── 接続先 IP の検証 (DNS リバインディング対策) ───────────────────────────


async def test_guard_blocks_host_resolving_to_private_at_connect(private_networks_blocked):
    """事前検証を通っても、接続時に内部アドレスへ解決されたら接続しない。"""
    answers = iter(["93.184.216.34", "127.0.0.1"])

    def rebinding(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (next(answers), 0))]

    from app.utils.network import is_safe_url

    with patch("app.utils.network.socket.getaddrinfo", side_effect=rebinding):
        assert is_safe_url("http://rebind.example/") is True
        async with make_async_client(use_proxy=False, ssrf_guard=True) as client:
            with pytest.raises(httpx.ConnectError, match="Blocked"):
                await client.get("http://rebind.example/")


async def test_guard_connects_to_validated_ip(private_networks_blocked):
    """名前解決で検証した IP にそのまま接続する (再解決しない)。"""

    async def serve(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        # public.example は実在しないので、検証済み IP 以外へは接続できない
        with patch(
            "app.utils.network.resolve_and_validate_host", return_value=["127.0.0.1"]
        ) as resolver:
            async with make_async_client(use_proxy=False, ssrf_guard=True) as client:
                resp = await client.get(f"http://public.example:{port}/")
        assert resp.status_code == 200
        assert resp.text == "ok"
        resolver.assert_called_once_with("public.example")
    finally:
        server.close()
        await server.wait_closed()


async def test_guard_skipped_when_private_networks_allowed():
    with patch("app.config.settings.allow_private_networks", True):
        async with make_async_client(use_proxy=False, ssrf_guard=True) as client:
            # 検証をスキップしてホスト名のまま接続を試みる (接続拒否になる)
            with pytest.raises(httpx.ConnectError) as exc_info:
                await client.get("http://127.0.0.1:9/")
    assert "Blocked" not in str(exc_info.value)
