"""フォワードプロキシ対応のオプション付き httpx.AsyncClient ファクトリ。"""

import httpx

from app import __version__
from app.config import settings

USER_AGENT = f"Nekonoverse/{__version__}"


def get_proxy_url() -> str | None:
    """設定からプロキシ URL を返す。https_proxy を優先する。"""
    return settings.https_proxy or settings.http_proxy


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
    kwargs.setdefault("proxy", None)
    return httpx.AsyncClient(**kwargs)


def make_media_transform_client(**kwargs) -> httpx.AsyncClient:
    """media-proxy-transform サービス用の httpx.AsyncClient を作成する。"""
    _inject_user_agent(kwargs)
    if settings.media_proxy_transform_uds:
        kwargs.setdefault(
            "transport", httpx.AsyncHTTPTransport(uds=settings.media_proxy_transform_uds)
        )
    kwargs.setdefault("timeout", 15.0)
    kwargs.setdefault("proxy", None)
    return httpx.AsyncClient(**kwargs)


def make_summary_proxy_client(**kwargs) -> httpx.AsyncClient:
    """summary-proxy サービス用に設定された httpx.AsyncClient を作成する。"""
    _inject_user_agent(kwargs)
    if settings.summary_proxy_uds:
        kwargs.setdefault(
            "transport", httpx.AsyncHTTPTransport(uds=settings.summary_proxy_uds)
        )
    kwargs.setdefault("timeout", 15.0)
    kwargs.setdefault("proxy", None)
    return httpx.AsyncClient(**kwargs)


def make_neko_search_client(**kwargs) -> httpx.AsyncClient:
    """neko-search サービス用に設定された httpx.AsyncClient を作成する。"""
    _inject_user_agent(kwargs)
    if settings.neko_search_uds:
        kwargs.setdefault(
            "transport", httpx.AsyncHTTPTransport(uds=settings.neko_search_uds)
        )
    kwargs.setdefault("timeout", 10.0)
    kwargs.setdefault("proxy", None)
    return httpx.AsyncClient(**kwargs)


def make_async_client(*, use_proxy: bool = True, **kwargs) -> httpx.AsyncClient:
    """プロキシ設定を注入した httpx.AsyncClient を作成する。

    Args:
        use_proxy: True (デフォルト) の場合、設定からプロキシを注入する。
                   ローカル/内部サービス呼び出しには False を設定する。
        **kwargs: httpx.AsyncClient に渡される追加の引数。
    """
    _inject_user_agent(kwargs)
    if use_proxy and "proxy" not in kwargs:
        proxy_url = get_proxy_url()
        if proxy_url:
            kwargs["proxy"] = proxy_url
    # プロキシが不要な場合、httpx が HTTP_PROXY 環境変数を
    # 自動検出するのを防ぐため明示的に None を設定する。
    if not use_proxy:
        kwargs.setdefault("proxy", None)
    return httpx.AsyncClient(**kwargs)
