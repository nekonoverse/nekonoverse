"""Network security utilities (SSRF protection)."""

import ipaddress
import socket
from urllib.parse import urlparse


def is_private_host(hostname: str) -> bool:
    """Block requests to private/loopback IP ranges (SSRF protection)."""
    from app.config import settings

    if settings.allow_private_networks:
        return False
    try:
        for info in socket.getaddrinfo(hostname, None):
            addr = ipaddress.ip_address(info[4][0])
            if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
                return True
    except (socket.gaierror, ValueError):
        return True  # can't resolve → block
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
            if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
                raise ValueError(f"Private IP address detected: {addr}")
            addrs.append(str(addr))
        if not addrs:
            raise ValueError(f"No addresses resolved for {hostname}")
        return addrs
    except (socket.gaierror, ValueError) as e:
        raise ValueError(f"DNS resolution failed for {hostname}: {e}")


def is_safe_url(url: str) -> bool:
    """Check if a URL is safe for outbound requests (http/https, non-private host)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    if is_private_host(parsed.hostname):
        return False
    return True
