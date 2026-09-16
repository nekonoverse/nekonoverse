"""ネットワークセキュリティユーティリティ (SSRF 保護)。"""

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urljoin, urlparse

import httpx


def _is_blocked_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """外部リクエストの接続先として許可しない IP アドレスか判定する。"""
    # IPv4 射影アドレス (::ffff:127.0.0.1 等) は IPv4 として判定する
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_reserved
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_unspecified
    )


def is_private_host(hostname: str) -> bool:
    """プライベート/ループバック IP 範囲へのリクエストをブロックする (SSRF 保護)。"""
    from app.config import settings

    if settings.allow_private_networks:
        return False
    try:
        for info in socket.getaddrinfo(hostname, None):
            if _is_blocked_ip(ipaddress.ip_address(info[4][0])):
                return True
    except (socket.gaierror, ValueError):
        return True  # 解決不可 → ブロック
    return False


def resolve_and_validate_host(hostname: str) -> list[str]:
    """M-8: DNS rebinding対策 -- ホスト名を解決し、安全なIPアドレスのリストを返す。

    プライベートIPが含まれている場合はValueErrorを送出する。
    返されたIPアドレスを使って直接接続することでDNS rebindingを防止する。
    """
    from app.config import settings

    if settings.allow_private_networks:
        return []  # 検証スキップ

    try:
        addrs = []
        for info in socket.getaddrinfo(hostname, None):
            addr = ipaddress.ip_address(info[4][0])
            if _is_blocked_ip(addr):
                raise ValueError(f"Private IP address detected: {addr}")
            if str(addr) not in addrs:
                addrs.append(str(addr))
        if not addrs:
            raise ValueError(f"No addresses resolved for {hostname}")
        return addrs
    except (socket.gaierror, ValueError) as e:
        raise ValueError(f"DNS resolution failed for {hostname}: {e}")


def is_safe_url(url: str) -> bool:
    """URL が外部リクエストに安全か確認する (http/https、非プライベートホスト)。"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    if is_private_host(parsed.hostname):
        return False
    return True


class UnsafeURLError(Exception):
    """外部リクエスト先 (リダイレクト先を含む) が SSRF 保護で拒否された。"""


async def safe_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers_for: Callable[[str], dict[str, str]] | None = None,
    max_redirects: int = 5,
) -> httpx.Response:
    """リダイレクトを手動で追跡し、各ホップの URL を SSRF 検証する GET。

    httpx の follow_redirects=True では初回 URL しか検証できず、外部サーバーが
    内部アドレスへリダイレクトさせると内部サービスへ到達してしまうため。

    headers_for: ホップごとのリクエストヘッダーを返す関数 (HTTP Signature は
        URL ごとに署名し直す必要がある)。

    Raises:
        UnsafeURLError: 初回 URL またはリダイレクト先が安全でない。
        httpx.TooManyRedirects: リダイレクト回数の上限を超えた。
    """
    current = url
    for _ in range(max_redirects + 1):
        if not is_safe_url(current):
            raise UnsafeURLError(current)
        headers = headers_for(current) if headers_for else None
        resp = await client.get(current, headers=headers, follow_redirects=False)
        if not resp.is_redirect:
            return resp
        current = urljoin(current, resp.headers["location"])
    raise httpx.TooManyRedirects(f"Too many redirects: {url}")
