"""Tests for app.utils.http_client (forward proxy support)."""

from unittest.mock import patch

from app.utils.http_client import get_proxy_url, make_async_client


class TestGetProxyUrl:
    def test_no_proxy_configured(self):
        with patch("app.utils.http_client.settings") as mock:
            mock.https_proxy = None
            mock.http_proxy = None
            assert get_proxy_url() is None

    def test_https_proxy_preferred(self):
        with patch("app.utils.http_client.settings") as mock:
            mock.https_proxy = "http://proxy:8080"
            mock.http_proxy = "http://other:3128"
            assert get_proxy_url() == "http://proxy:8080"

    def test_http_proxy_fallback(self):
        with patch("app.utils.http_client.settings") as mock:
            mock.https_proxy = None
            mock.http_proxy = "http://proxy:3128"
            assert get_proxy_url() == "http://proxy:3128"


class TestMakeAsyncClient:
    def test_no_proxy_when_not_configured(self):
        with patch("app.utils.http_client.settings") as mock:
            mock.https_proxy = None
            mock.http_proxy = None
            client = make_async_client(timeout=10.0)
            assert client is not None
            # プロキシ未設定: _mountsにプロキシ用エントリなし
            assert len(client._mounts) == 0

    def test_proxy_injected_when_configured(self):
        with patch("app.utils.http_client.settings") as mock:
            mock.https_proxy = "http://proxy:8080"
            mock.http_proxy = None
            client = make_async_client(timeout=10.0)
            assert client is not None
            # プロキシ設定時: _mountsにプロキシ用エントリが追加される
            assert len(client._mounts) == 1

    def test_use_proxy_false_skips_proxy(self):
        with patch("app.utils.http_client.settings") as mock:
            mock.https_proxy = "http://proxy:8080"
            mock.http_proxy = None
            client = make_async_client(use_proxy=False, timeout=10.0)
            assert client is not None
            assert len(client._mounts) == 0

    def test_explicit_proxy_not_overridden(self):
        with patch("app.utils.http_client.settings") as mock:
            mock.https_proxy = "http://settings-proxy:8080"
            mock.http_proxy = None
            # 明示的にproxyを指定した場合、settings値で上書きしない
            client = make_async_client(
                proxy="http://custom:3128", timeout=10.0,
            )
            assert client is not None
            assert len(client._mounts) == 1

    def test_kwargs_passed_through(self):
        with patch("app.utils.http_client.settings") as mock:
            mock.https_proxy = None
            mock.http_proxy = None
            client = make_async_client(
                timeout=5.0, follow_redirects=True, max_redirects=3,
            )
            assert client is not None
