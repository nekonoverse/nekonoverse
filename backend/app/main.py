from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

_DEFAULT_FAVICON_SVG = b"""\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 180 180" fill="none">
  <rect width="180" height="180" rx="36" fill="#f5e6f0"/>
  <path d="M45 73 L62 28 L79 67Z" fill="#f9a8d4"/>
  <path d="M135 73 L118 28 L101 67Z" fill="#f9a8d4"/>
  <path d="M50 70 L62 37 L73 67Z" fill="#fce4ec"/>
  <path d="M130 70 L118 37 L107 67Z" fill="#fce4ec"/>
  <circle cx="90" cy="101" r="42" fill="#fff5f5"/>
  <circle cx="62" cy="112" r="8" fill="#fbb4c8" opacity="0.5"/>
  <circle cx="118" cy="112" r="8" fill="#fbb4c8" opacity="0.5"/>
  <ellipse cx="73" cy="95" rx="6" ry="7" fill="#5b4a6a"/>
  <ellipse cx="107" cy="95" rx="6" ry="7" fill="#5b4a6a"/>
  <circle cx="75" cy="93" r="2" fill="#fff"/>
  <circle cx="109" cy="93" r="2" fill="#fff"/>
  <path d="M87 107 L90 111 L93 107Z" fill="#f9a8d4"/>
  <path d="M82 114 Q90 121 98 114" stroke="#c48b9f" stroke-width="2" fill="none" stroke-linecap="round"/>
  <line x1="42" y1="104" x2="65" y2="107" stroke="#d4a0b9" stroke-width="1.5" stroke-linecap="round"/>
  <line x1="42" y1="112" x2="65" y2="112" stroke="#d4a0b9" stroke-width="1.5" stroke-linecap="round"/>
  <line x1="115" y1="107" x2="138" y2="104" stroke="#d4a0b9" stroke-width="1.5" stroke-linecap="round"/>
  <line x1="115" y1="112" x2="138" y2="112" stroke="#d4a0b9" stroke-width="1.5" stroke-linecap="round"/>
</svg>"""
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from app import VERSION as __version__
from app.activitypub.nodeinfo import router as nodeinfo_router
from app.activitypub.routes import router as ap_router
from app.activitypub.webfinger import router as webfinger_router
from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.invites import router as invites_router
from app.api.mastodon.accounts import relationships_router
from app.api.mastodon.accounts import router as accounts_router
from app.api.mastodon.bookmarks import router as bookmarks_router
from app.api.mastodon.compat import router as compat_router
from app.api.mastodon.follow_requests import router as follow_requests_router
from app.api.mastodon.media_proxy import router as media_proxy_router
from app.api.mastodon.notifications import router as notifications_router
from app.api.mastodon.polls import router as polls_router
from app.api.mastodon.push import router as push_router
from app.api.mastodon.search import router as search_router
from app.api.mastodon.statuses import router as statuses_router
from app.api.mastodon.streaming import router as streaming_router
from app.api.mastodon.timelines import router as timelines_router
from app.api.media import router as media_router
from app.api.oauth import router as oauth_router
from app.api.passkey import router as passkey_router
from app.config import settings
from app.dependencies import get_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging

    import httpx

    from app.storage import ensure_bucket

    try:
        await ensure_bucket()
    except Exception as e:
        logging.getLogger(__name__).warning("Could not ensure S3 bucket: %s", e)

    from app.config import settings as app_settings
    from app.utils.http_client import make_async_client

    app.state.http_client = make_async_client(
        timeout=30.0,
        verify=not app_settings.skip_ssl_verify,
        follow_redirects=True,
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )

    # 起動時にDB保存されたVAPID鍵をメモリキャッシュにロード
    try:
        from app.database import async_session
        from app.services.push_service import load_db_vapid_key_async

        async with async_session() as startup_db:
            await load_db_vapid_key_async(startup_db)
    except Exception as e:
        logging.getLogger(__name__).warning("Could not load VAPID key: %s", e)

    # デフォルトサーバーアイコンの自動生成（初回起動時）
    try:
        from app.database import async_session as _as
        from app.services.icon_service import ensure_default_icons

        async with _as() as icon_db:
            await ensure_default_icons(icon_db)
    except Exception as e:
        logging.getLogger(__name__).warning("Could not ensure default icons: %s", e)

    # システムアカウントの自動作成
    try:
        from app.database import async_session as _sa
        from app.services.system_account_service import ensure_system_accounts

        async with _sa() as sys_db:
            await ensure_system_accounts(sys_db)
    except Exception as e:
        logging.getLogger(__name__).warning("Could not ensure system accounts: %s", e)

    from app.pubsub_hub import pubsub_hub

    await pubsub_hub.start()
    try:
        yield
    finally:
        await pubsub_hub.stop()
        await app.state.http_client.aclose()


app = FastAPI(
    title="Nekonoverse",
    version="0.1.0",
    description="ActivityPub server with Misskey-compatible emoji reactions",
    lifespan=lifespan,
)

cors_origins = [
    "http://localhost:3000",
    settings.server_url,
]
# Allow frontend URL configured via environment
if settings.frontend_url and settings.frontend_url not in cors_origins:
    cors_origins.append(settings.frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)


async def _build_contact(db) -> dict:
    """Build Mastodon-compatible contact object with admin account."""
    from sqlalchemy import select

    from app.models.actor import Actor
    from app.models.user import User
    from app.utils.media_proxy import media_proxy_url

    fallback = {"email": "", "account": None}
    try:
        result = await db.execute(
            select(User)
            .where(User.role == "admin", User.is_active.is_(True), User.is_system.is_(False))
            .limit(1)
        )
        admin_user = result.scalar_one_or_none()
        if not admin_user:
            return fallback
        result2 = await db.execute(
            select(Actor).where(Actor.id == admin_user.actor_id)
        )
        actor = result2.scalar_one_or_none()
        if not actor:
            return fallback
        return {
            "email": admin_user.email or "",
            "account": {
                "id": str(admin_user.id),
                "username": actor.username,
                "acct": actor.username,
                "email": "",
                "display_name": actor.display_name or "",
                "note": actor.summary or "",
                "avatar": media_proxy_url(actor.avatar_url) or "/default-avatar.svg",
                "avatar_static": media_proxy_url(actor.avatar_url) or "/default-avatar.svg",
                "header": media_proxy_url(actor.header_url) or "",
                "header_static": media_proxy_url(actor.header_url) or "",
                "url": f"{settings.server_url}/@{actor.username}",
                "created_at": admin_user.created_at.isoformat() if admin_user.created_at else "",
                "bot": actor.is_bot,
                "locked": actor.manually_approves_followers,
                "discoverable": actor.discoverable,
                "followers_count": 0,
                "following_count": 0,
                "statuses_count": 0,
                "last_status_at": None,
                "fields": [],
                "emojis": [],
            },
        }
    except Exception:
        return fallback


@app.get("/api/v1/instance")
async def instance_info(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import func, select

    from app.models.actor import Actor
    from app.models.note import Note
    from app.models.user import User
    from app.services.server_settings_service import get_setting

    thumbnail_url = None
    title = "Nekonoverse"
    description = "A cat-friendly ActivityPub server"
    registration_open = settings.registration_open
    registration_mode = "open"
    theme_color = None
    try:
        icon_url = await get_setting(db, "server_icon_url")
        if icon_url:
            thumbnail_url = icon_url
        name = await get_setting(db, "server_name")
        if name:
            title = name
        desc = await get_setting(db, "server_description")
        if desc:
            description = desc
        mode = await get_setting(db, "registration_mode")
        if mode is not None:
            registration_mode = mode
            registration_open = mode != "closed"
        else:
            reg = await get_setting(db, "registration_open")
            if reg is not None:
                registration_open = reg == "true"
            registration_mode = "open" if registration_open else "closed"
        tc = await get_setting(db, "server_theme_color")
        if tc:
            theme_color = tc
    except Exception:
        pass

    # サーバー統計を実際のデータベースから取得
    user_count = 0
    status_count = 0
    domain_count = 0
    try:
        # システムアカウントをユーザー数から除外
        user_result = await db.execute(
            select(func.count())
            .select_from(Actor)
            .join(User, User.actor_id == Actor.id)
            .where(Actor.domain.is_(None), User.is_system.is_(False))
        )
        user_count = user_result.scalar() or 0

        status_result = await db.execute(
            select(func.count()).select_from(Note).where(Note.local.is_(True))
        )
        status_count = status_result.scalar() or 0

        domain_result = await db.execute(
            select(func.count(func.distinct(Actor.domain))).where(Actor.domain.isnot(None))
        )
        domain_count = domain_result.scalar() or 0
    except Exception:
        pass

    # VAPID公開鍵 (Web Push用、push_enabledの場合のみ)
    vapid_key = None
    try:
        from app.services.push_service import get_vapid_public_key_base64url, is_push_enabled

        if await is_push_enabled(db):
            vapid_key = get_vapid_public_key_base64url()
    except Exception:
        pass

    contact_info = await _build_contact(db)

    resp: dict = {
        "uri": settings.domain,
        "title": title,
        "description": description,
        "short_description": description,
        "version": __version__,
        "urls": {
            "streaming_api": f"wss://{settings.domain}/api/v1/streaming",
        },
        "stats": {
            "user_count": user_count,
            "status_count": status_count,
            "domain_count": domain_count,
        },
        "registrations": registration_open,
        "registration_mode": registration_mode,
        "languages": ["ja", "en"],
        "rules": [],
        "email": contact_info.get("email", ""),
        "contact_account": contact_info.get("account"),
        "contact": contact_info,
        "configuration": {
            "statuses": {
                "max_characters": 5000,
                "max_media_attachments": 4,
                "characters_reserved_per_url": 23,
            },
            "media_attachments": {
                "supported_mime_types": [
                    "image/jpeg", "image/png", "image/gif", "image/webp",
                ],
                "image_size_limit": 10485760,
                "image_matrix_limit": 16777216,
                "video_size_limit": 41943040,
                "video_frame_rate_limit": 60,
                "video_matrix_limit": 8294400,
            },
            "polls": {
                "max_options": 10,
                "max_characters_per_option": 200,
                "min_expiration": 300,
                "max_expiration": 2592000,
            },
        },
    }
    if vapid_key:
        resp["vapid_key"] = vapid_key
    if thumbnail_url:
        resp["thumbnail"] = {"url": thumbnail_url}
    if theme_color:
        resp["theme_color"] = theme_color

    # Legal page URLs
    try:
        tos_content = await get_setting(db, "terms_of_service")
        if tos_content:
            resp["tos_url"] = f"https://{settings.domain}/terms"
        else:
            tos_url = await get_setting(db, "tos_url")
            if tos_url:
                resp["tos_url"] = tos_url
        pp_content = await get_setting(db, "privacy_policy")
        if pp_content:
            resp["privacy_policy_url"] = f"https://{settings.domain}/privacy"
    except Exception:
        pass

    return resp


_LEGAL_ALLOWED_TAGS = [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "br", "hr",
    "strong", "em", "code", "pre", "blockquote",
    "ul", "ol", "li",
    "a",
    "table", "thead", "tbody", "tr", "th", "td",
]


def _render_legal_markdown(raw: str) -> str:
    import bleach
    import markdown

    html = markdown.markdown(raw, extensions=["tables", "fenced_code"])
    return bleach.clean(html, tags=_LEGAL_ALLOWED_TAGS, attributes={"a": ["href"]}, strip=True)


@app.get("/api/v1/instance/terms")
async def get_instance_terms(db: AsyncSession = Depends(get_db)):
    """Return terms of service content (public, no auth required)."""
    from app.services.server_settings_service import get_setting

    raw = await get_setting(db, "terms_of_service")
    if not raw:
        return {"content_html": None, "content_raw": None}
    return {"content_html": _render_legal_markdown(raw), "content_raw": raw}


@app.get("/api/v1/instance/privacy")
async def get_instance_privacy(db: AsyncSession = Depends(get_db)):
    """Return privacy policy content (public, no auth required)."""
    from app.services.server_settings_service import get_setting

    raw = await get_setting(db, "privacy_policy")
    if not raw:
        return {"content_html": None, "content_raw": None}
    return {"content_html": _render_legal_markdown(raw), "content_raw": raw}


@app.get("/manifest.webmanifest")
async def manifest(db: AsyncSession = Depends(get_db)):
    from fastapi.responses import JSONResponse

    from app.services.server_settings_service import get_setting

    name = await get_setting(db, "server_name") or "Nekonoverse"
    icon_192 = await get_setting(db, "pwa_icon_192_url")
    icon_512 = await get_setting(db, "pwa_icon_512_url")
    theme_color = await get_setting(db, "server_theme_color") or "#f5e6f0"

    if icon_512:
        src_192 = icon_192 or icon_512
        icons = [
            {"src": src_192, "sizes": "192x192", "type": "image/png"},
            {"src": icon_512, "sizes": "512x512", "type": "image/png"},
            {
                "src": icon_512,
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ]
    else:
        icons = [
            {"src": "/pwa-192x192.svg", "sizes": "192x192", "type": "image/svg+xml"},
            {"src": "/pwa-512x512.svg", "sizes": "512x512", "type": "image/svg+xml"},
            {
                "src": "/pwa-512x512.svg",
                "sizes": "512x512",
                "type": "image/svg+xml",
                "purpose": "maskable",
            },
        ]

    return JSONResponse(
        content={
            "name": name,
            "short_name": name,
            "description": "A cozy Fediverse social network",
            "theme_color": theme_color,
            "background_color": theme_color,
            "display": "standalone",
            "scope": "/",
            "start_url": "/",
            "icons": icons,
        },
        media_type="application/manifest+json",
    )


@app.get("/favicon.ico")
async def favicon_ico(db: AsyncSession = Depends(get_db)):
    from fastapi.responses import RedirectResponse, Response

    from app.services.server_settings_service import get_setting

    url = await get_setting(db, "favicon_ico_url")
    if url:
        return RedirectResponse(url=url, status_code=302)

    # Default: serve the built-in SVG cat icon
    return Response(content=_DEFAULT_FAVICON_SVG, media_type="image/svg+xml")


@app.get("/api/v1/custom_emojis")
async def list_custom_emojis(db: AsyncSession = Depends(get_db)):
    import json

    from app.valkey_client import valkey as valkey_client

    # Valkeyキャッシュ (絵文字リストは頻繁に変わらない)
    cache_key = "perf:custom_emojis"
    try:
        cached = await valkey_client.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    from app.services.emoji_service import list_local_emojis

    emojis = await list_local_emojis(db)
    result = [
        {
            "shortcode": e.shortcode,
            "url": e.url,
            "static_url": e.static_url or e.url,
            "visible_in_picker": e.visible_in_picker,
            "category": e.category,
            "aliases": e.aliases or [],
            "license": e.license,
            "is_sensitive": e.is_sensitive,
        }
        for e in emojis
    ]

    try:
        await valkey_client.set(cache_key, json.dumps(result), ex=300)
    except Exception:
        pass

    return result


@app.get("/api/v1/trends/tags")
async def trending_tags(
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
):
    from app.services.hashtag_service import get_trending_tags

    tags = await get_trending_tags(db, limit=limit)
    return [
        {
            "name": tag.name,
            "url": f"{settings.server_url}/tags/{tag.name}",
            "history": [],
        }
        for tag in tags
    ]


@app.get("/api/v1/health")
async def health():
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(relationships_router)
app.include_router(accounts_router)
app.include_router(notifications_router)
app.include_router(push_router)
app.include_router(bookmarks_router)
app.include_router(follow_requests_router)
app.include_router(polls_router)
app.include_router(statuses_router)
app.include_router(timelines_router)
app.include_router(streaming_router)
app.include_router(search_router)
app.include_router(compat_router)
app.include_router(oauth_router)
app.include_router(passkey_router)
app.include_router(media_proxy_router)
app.include_router(media_router)
app.include_router(admin_router)
app.include_router(invites_router)
app.include_router(webfinger_router)
app.include_router(nodeinfo_router)
app.include_router(ap_router)
