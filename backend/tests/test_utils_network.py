"""Tests for app.utils.network (SSRF protection utilities)."""

import socket
from unittest.mock import patch

import pytest

from app.utils.network import is_private_host, is_safe_url, resolve_and_validate_host

# ---------------------------------------------------------------------------
# is_private_host
# ---------------------------------------------------------------------------


@patch("app.utils.network.socket.getaddrinfo")
def test_is_private_host_public_ip(mock_dns):
    """is_private_host returns False for a public IP address."""
    mock_dns.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
    assert is_private_host("example.com") is False


@patch("app.utils.network.socket.getaddrinfo")
def test_is_private_host_loopback(mock_dns):
    """is_private_host returns True for loopback address 127.0.0.1."""
    mock_dns.return_value = [(2, 1, 6, "", ("127.0.0.1", 0))]
    assert is_private_host("localhost") is True


@patch("app.utils.network.socket.getaddrinfo")
def test_is_private_host_private_range(mock_dns):
    """is_private_host returns True for private IP ranges (192.168.x.x, 10.x.x.x)."""
    mock_dns.return_value = [(2, 1, 6, "", ("192.168.1.1", 0))]
    assert is_private_host("internal.local") is True

    mock_dns.return_value = [(2, 1, 6, "", ("10.0.0.1", 0))]
    assert is_private_host("another-internal.local") is True


@patch("app.utils.network.socket.getaddrinfo")
def test_is_private_host_dns_failure(mock_dns):
    """is_private_host returns True (fail-closed) when DNS resolution fails."""
    mock_dns.side_effect = socket.gaierror("DNS lookup failed")
    assert is_private_host("nonexistent.invalid") is True


@patch("app.config.settings")
def test_is_private_host_allow_private_networks(mock_settings):
    """is_private_host returns False when allow_private_networks is True."""
    mock_settings.allow_private_networks = True
    assert is_private_host("localhost") is False
    assert is_private_host("192.168.1.1") is False


# ---------------------------------------------------------------------------
# resolve_and_validate_host
# ---------------------------------------------------------------------------


@patch("app.utils.network.socket.getaddrinfo")
def test_resolve_and_validate_host_public(mock_dns):
    """resolve_and_validate_host returns list of IPs for a public host."""
    mock_dns.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
    result = resolve_and_validate_host("example.com")
    assert result == ["93.184.216.34"]


@patch("app.utils.network.socket.getaddrinfo")
def test_resolve_and_validate_host_private(mock_dns):
    """resolve_and_validate_host raises ValueError for private IPs."""
    mock_dns.return_value = [(2, 1, 6, "", ("192.168.1.1", 0))]
    with pytest.raises(ValueError, match="Private IP address detected"):
        resolve_and_validate_host("internal.local")


@patch("app.utils.network.socket.getaddrinfo")
def test_resolve_and_validate_host_dns_failure(mock_dns):
    """resolve_and_validate_host raises ValueError when DNS resolution fails."""
    mock_dns.side_effect = socket.gaierror("DNS lookup failed")
    with pytest.raises(ValueError, match="DNS resolution failed"):
        resolve_and_validate_host("nonexistent.invalid")


@patch("app.config.settings")
def test_resolve_and_validate_host_allow_private(mock_settings):
    """resolve_and_validate_host returns empty list when allow_private_networks is True."""
    mock_settings.allow_private_networks = True
    result = resolve_and_validate_host("localhost")
    assert result == []


# ---------------------------------------------------------------------------
# is_safe_url
# ---------------------------------------------------------------------------


@patch("app.utils.network.socket.getaddrinfo")
def test_is_safe_url_valid(mock_dns):
    """is_safe_url returns True for a valid https URL with public IP."""
    mock_dns.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
    assert is_safe_url("https://example.com") is True


@patch("app.utils.network.socket.getaddrinfo")
def test_is_safe_url_private(mock_dns):
    """is_safe_url returns False for a URL that resolves to a private IP."""
    mock_dns.return_value = [(2, 1, 6, "", ("127.0.0.1", 0))]
    assert is_safe_url("https://localhost") is False


def test_is_safe_url_bad_scheme():
    """is_safe_url returns False for non-http/https schemes."""
    assert is_safe_url("ftp://example.com") is False
    assert is_safe_url("file:///etc/passwd") is False
    assert is_safe_url("javascript:alert(1)") is False


def test_is_safe_url_no_hostname():
    """is_safe_url returns False when URL has no hostname."""
    assert is_safe_url("not-a-url") is False
    assert is_safe_url("") is False
    assert is_safe_url("http://") is False
