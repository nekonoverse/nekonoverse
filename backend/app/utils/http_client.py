"""フォワードプロキシ対応のオプション付き httpx.AsyncClient ファクトリ。"""

from collections.abc import Iterable
from typing import Any

import anyio
import httpcore
import httpx

from app import __version__
from app.config import settings

USER_AGENT = f"Nekonoverse/{__version__}"


class _SSRFGuardBackend(httpcore.AsyncNetworkBackend):
    """接続時に名前解決と SSRF 検証を行い、検証済みの IP へ直接接続するバックエンド。

    事前の is_safe_url() と実際の接続で別々に名前解決すると、DNS リバインディングで
    検証後に内部アドレスへ接続させられるため、検証した IP をそのまま接続に使う。
    TLS の SNI / 証明書検証には httpcore が元のホスト名を使うため影響しない。
    """

    def __init__(self) -> None:
        self._backend = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        from app.utils.network import resolve_and_validate_host

        try:
            addrs = await anyio.to_thread.run_sync(resolve_and_validate_host, host)
        except ValueError as exc:
            raise httpcore.ConnectError(f"Blocked connection to {host}: {exc}") from exc
        # allow_private_networks 有効時は検証をスキップし空リストが返る
        targets = addrs or [host]
        last_exc: Exception | None = None
        for target in targets:
            try:
                return await self._backend.connect_tcp(
                    target,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_exc = exc
        assert last_exc is not None
        raise last_exc

    async def connect_unix_socket(
        self, path: str, timeout: float | None = None, socket_options: Iterable[Any] | None = None
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("Unix socket connections are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class SSRFGuardTransport(httpx.AsyncHTTPTransport):
    """接続先 IP を SSRF 検証する httpx トランスポート (プロキシ非経由の通信用)。"""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # httpx は network_backend を受け付けないため、生成済みプールに差し込む
        self._pool._network_backend = _SSRFGuardBackend()


def get_proxy_url() -> str | None:
    """設定からプロキシ URL を返す。https_proxy を優先する。"""
    return settings.https_proxy or settings.http_proxy


def _disable_proxy(kwargs: dict) -> None:
    """明示的なプロキシ指定がなければプロキシを使わない設定にする。

    httpx は proxy=None でも trust_env が有効だと HTTP_PROXY 等の環境変数から
    プロキシを設定するため、環境変数の読み込みも止める。
    """
    if kwargs.get("proxy") is None:
        kwargs["proxy"] = None
        kwargs.setdefault("trust_env", False)


def _inject_user_agent(kwargs: dict) -> None:
    """kwargs に User-Agent ヘッダーが存在することを保証する。"""
    headers = kwargs.get("headers")
    if headers is None:
        kwargs["headers"] = {"User-Agent": USER_AGENT}
    elif isinstance(headers, dict) and "User-Agent" not in headers:
        headers["User-Agent"] = USER_AGENT


def make_face_detect_client(**kwargs) -> httpx.AsyncClient:
    """face-detect サービス用に設定された httpx.AsyncClient を作成する。

    ``settings.face_detect_uds`` が設定されている場合、TCP の代わりに
    Unix ドメインソケットトランスポートを使用する。

    face-detect は通常内部サービスのため、httpx が ``HTTP_PROXY``
    環境変数を使用するのを防ぐためプロキシはデフォルトで明示的に無効化。
    """
    _inject_user_agent(kwargs)
    if settings.face_detect_uds:
        kwargs.setdefault(
            "transport", httpx.AsyncHTTPTransport(uds=settings.face_detect_uds)
        )
    kwargs.setdefault("timeout", 30.0)
    _disable_proxy(kwargs)
    return httpx.AsyncClient(**kwargs)


def make_media_transform_client(**kwargs) -> httpx.AsyncClient:
    """media-proxy-transform サービス用の httpx.AsyncClient を作成する。"""
    _inject_user_agent(kwargs)
    if settings.media_proxy_transform_uds:
        kwargs.setdefault(
            "transport", httpx.AsyncHTTPTransport(uds=settings.media_proxy_transform_uds)
        )
    kwargs.setdefault("timeout", 15.0)
    _disable_proxy(kwargs)
    return httpx.AsyncClient(**kwargs)


def make_summary_proxy_client(**kwargs) -> httpx.AsyncClient:
    """summary-proxy サービス用に設定された httpx.AsyncClient を作成する。"""
    _inject_user_agent(kwargs)
    if settings.summary_proxy_uds:
        kwargs.setdefault(
            "transport", httpx.AsyncHTTPTransport(uds=settings.summary_proxy_uds)
        )
    kwargs.setdefault("timeout", 15.0)
    _disable_proxy(kwargs)
    return httpx.AsyncClient(**kwargs)


def make_neko_search_client(**kwargs) -> httpx.AsyncClient:
    """neko-search サービス用に設定された httpx.AsyncClient を作成する。"""
    _inject_user_agent(kwargs)
    if settings.neko_search_uds:
        kwargs.setdefault(
            "transport", httpx.AsyncHTTPTransport(uds=settings.neko_search_uds)
        )
    kwargs.setdefault("timeout", 10.0)
    _disable_proxy(kwargs)
    return httpx.AsyncClient(**kwargs)


def make_neko_vision_client(**kwargs) -> httpx.AsyncClient:
    """neko-vision サービス用に設定された httpx.AsyncClient を作成する。"""
    _inject_user_agent(kwargs)
    if settings.neko_vision_uds:
        kwargs.setdefault(
            "transport", httpx.AsyncHTTPTransport(uds=settings.neko_vision_uds)
        )
    kwargs.setdefault("timeout", 30.0)
    _disable_proxy(kwargs)
    return httpx.AsyncClient(**kwargs)


def make_video_thumb_client(**kwargs) -> httpx.AsyncClient:
    """video-thumb サービス用に設定された httpx.AsyncClient を作成する。"""
    _inject_user_agent(kwargs)
    if settings.video_thumb_uds:
        kwargs.setdefault(
            "transport", httpx.AsyncHTTPTransport(uds=settings.video_thumb_uds)
        )
    kwargs.setdefault("timeout", 60.0)
    _disable_proxy(kwargs)
    return httpx.AsyncClient(**kwargs)


def make_async_client(
    *, use_proxy: bool = True, ssrf_guard: bool = False, **kwargs
) -> httpx.AsyncClient:
    """プロキシ設定を注入した httpx.AsyncClient を作成する。

    Args:
        use_proxy: True (デフォルト) の場合、設定からプロキシを注入する。
                   ローカル/内部サービス呼び出しには False を設定する。
        ssrf_guard: True の場合、接続先 IP を接続直前に検証する。リモートサーバーが
                   指定した URL へ接続するクライアントでは必ず有効にする。
                   フォワードプロキシ経由の通信では名前解決がプロキシ側で行われるため
                   この検証は効かず、プロキシ側での制限が必要。
        **kwargs: httpx.AsyncClient に渡される追加の引数。
    """
    _inject_user_agent(kwargs)
    if ssrf_guard and "transport" not in kwargs:
        transport_kwargs = {
            k: kwargs[k] for k in ("verify", "limits", "http1", "http2") if k in kwargs
        }
        kwargs["transport"] = SSRFGuardTransport(**transport_kwargs)
    if use_proxy and "proxy" not in kwargs:
        proxy_url = get_proxy_url()
        if proxy_url:
            kwargs["proxy"] = proxy_url
    # プロキシが不要な場合、httpx が HTTP_PROXY 環境変数を
    # 自動検出するのを防ぐため明示的に None を設定する。
    if not use_proxy:
        _disable_proxy(kwargs)
    return httpx.AsyncClient(**kwargs)
