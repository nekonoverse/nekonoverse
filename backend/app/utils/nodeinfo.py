"""リモート nodeinfo の取得とソフトウェア検出。"""

import logging

import httpx

logger = logging.getLogger(__name__)

# EmojiReact activity タイプをサポートするソフトウェア名
_EMOJI_REACT_SOFTWARE = {"pleroma", "akkoma", "fedibird", "nekonoverse"}

# 絵文字リアクションをサポートするソフトウェア名 (EmojiReact または Like+_misskey_reaction)
_EMOJI_REACTION_SOFTWARE = _EMOJI_REACT_SOFTWARE | {"misskey", "calckey", "firefish", "sharkey"}

_CACHE_TTL = 86400  # 24 hours
_CACHE_TTL_FAIL = 3600  # 1 hour for failed fetches


async def get_domain_software(domain: str) -> str | None:
    """nodeinfo 経由でリモートインスタンスのソフトウェア名を取得する。

    結果は Valkey に 24 時間キャッシュされる。小文字のソフトウェア名
    (例: "pleroma", "misskey") を返すか、失敗時は None を返す。
    """
    name, _version, _instance_name = await get_domain_software_info(domain)
    return name


async def get_domain_software_info(
    domain: str,
) -> tuple[str | None, str | None, str | None]:
    """リモートインスタンスのソフトウェア名、バージョン、インスタンス名を取得する。

    結果は Valkey に 24 時間キャッシュされる。
    (lowercase_name, version, instance_name) または (None, None, None) を返す。
    """
    from app.valkey_client import valkey

    name_key = f"nodeinfo:software:{domain}"
    ver_key = f"nodeinfo:software_version:{domain}"
    iname_key = f"nodeinfo:instance_name:{domain}"

    cached_name = await valkey.get(name_key)
    if cached_name is not None:
        name_val = cached_name.decode() if isinstance(cached_name, bytes) else cached_name
        name = name_val if name_val != "" else None
        cached_ver = await valkey.get(ver_key)
        ver = None
        if cached_ver is not None:
            ver_val = cached_ver.decode() if isinstance(cached_ver, bytes) else cached_ver
            ver = ver_val if ver_val != "" else None
        cached_iname = await valkey.get(iname_key)
        iname = None
        if cached_iname is not None:
            iname_val = (
                cached_iname.decode()
                if isinstance(cached_iname, bytes)
                else cached_iname
            )
            iname = iname_val if iname_val != "" else None
        return name, ver, iname

    name, version, instance_name = await _fetch_software(domain)

    # 失敗した取得は早めにリトライするため短い TTL を使用
    ttl = _CACHE_TTL if (name or instance_name) else _CACHE_TTL_FAIL
    await valkey.set(name_key, name or "", ex=ttl)
    await valkey.set(ver_key, version or "", ex=ttl)
    await valkey.set(iname_key, instance_name or "", ex=ttl)
    return name, version, instance_name


async def _fetch_software(
    domain: str,
) -> tuple[str | None, str | None, str | None]:
    """リモート nodeinfo からソフトウェア名、バージョン、インスタンス名を取得する。"""
    try:
        from app.utils.http_client import USER_AGENT
        from app.utils.network import is_safe_url
        async with httpx.AsyncClient(
            timeout=5, follow_redirects=False, verify=False,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            # ステップ 1: nodeinfo URL をディスカバリ
            wellknown_url = f"https://{domain}/.well-known/nodeinfo"
            if not is_safe_url(wellknown_url):
                return None, None, None
            resp = await client.get(wellknown_url)
            if resp.status_code != 200:
                return None, None, None
            data = resp.json()
            links = data.get("links", [])

            nodeinfo_url = None
            for link in links:
                href = link.get("href", "")
                rel = link.get("rel", "")
                if "nodeinfo" in rel and href:
                    nodeinfo_url = href
                    break
            if not nodeinfo_url:
                return None, None, None

            # フェッチ前に nodeinfo URL を検証
            if not is_safe_url(nodeinfo_url):
                return None, None, None

            # ステップ 2: nodeinfo を取得
            resp = await client.get(nodeinfo_url)
            if resp.status_code != 200:
                return None, None, None
            info = resp.json()
            sw = info.get("software", {})
            name = sw.get("name", "")
            version = sw.get("version", "")
            metadata = info.get("metadata", {})
            instance_name = (
                metadata.get("nodeName")
                or metadata.get("name")
                or ""
            )

            # フォールバック: Mastodon 互換 API からインスタンス名を取得
            if not instance_name:
                instance_name = await _fetch_instance_name(client, domain)

            return (
                name.lower() if name else None,
                version if version else None,
                instance_name if instance_name else None,
            )
    except Exception:
        logger.debug("Failed to fetch nodeinfo for %s", domain, exc_info=True)
        return None, None, None


async def _fetch_instance_name(
    client: httpx.AsyncClient, domain: str
) -> str | None:
    """フォールバック: Mastodon 互換インスタンス API からインスタンスタイトルを取得する。"""
    for path in ("/api/v2/instance", "/api/v1/instance"):
        try:
            resp = await client.get(f"https://{domain}{path}")
            if resp.status_code != 200:
                continue
            data = resp.json()
            title = data.get("title") or ""
            if title:
                return title
        except Exception:
            continue
    return None


async def uses_emoji_react(domain: str) -> bool:
    """リモートドメインが EmojiReact activity タイプをサポートするかチェックする。"""
    software = await get_domain_software(domain)
    return software in _EMOJI_REACT_SOFTWARE


async def supports_emoji_reactions(domain: str) -> bool:
    """リモートドメインが何らかの形式の絵文字リアクションをサポートするかチェックする。

    EmojiReact または Like+_misskey_reaction を理解するサーバーには True を返す。
    Mastodon/GoToSocial/不明なサーバーには False を返す (絵文字リアクションが無意味なため)。
    """
    software = await get_domain_software(domain)
    return software in _EMOJI_REACTION_SOFTWARE


# 絵文字リアクションの内容を無視することが知られているソフトウェア (素の ❤ いいねとして表示)
_EMOJI_REACTION_BLOCKLIST = {"mastodon"}


async def ignores_emoji_reactions(domain: str) -> bool:
    """リモートドメインが絵文字リアクションの内容を無視することが知られているかチェックする。

    Mastodon には True を返す (content を破棄し常に ❤ を表示)。
    不明なサーバーには False を返す (疑わしきは罰せず)。
    """
    software = await get_domain_software(domain)
    return software in _EMOJI_REACTION_BLOCKLIST
