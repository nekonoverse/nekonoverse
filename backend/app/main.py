from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.activitypub.nodeinfo import router as nodeinfo_router
from app.activitypub.routes import router as ap_router
from app.activitypub.webfinger import router as webfinger_router
from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.invites import router as invites_router
from app.api.mastodon.accounts import relationships_router
from app.api.mastodon.accounts import router as accounts_router
from app.api.mastodon.bookmarks import router as bookmarks_router
from app.api.mastodon.media_proxy import router as media_proxy_router
from app.api.mastodon.notifications import router as notifications_router
from app.api.mastodon.polls import router as polls_router
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

    app.state.http_client = httpx.AsyncClient(
        timeout=30.0,
        verify=not app_settings.skip_ssl_verify,
        follow_redirects=True,
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )
    try:
        yield
    finally:
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
# Allow Tailscale / LAN access in debug mode
if settings.debug:
    cors_origins.append("http://100.68.9.116:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)


@app.get("/api/v1/instance")
async def instance_info(db: AsyncSession = Depends(get_db)):
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

    resp: dict = {
        "uri": settings.domain,
        "title": title,
        "description": description,
        "version": __version__,
        "urls": {},
        "stats": {"user_count": 0, "status_count": 0, "domain_count": 0},
        "registrations": registration_open,
        "registration_mode": registration_mode,
    }
    if thumbnail_url:
        resp["thumbnail"] = {"url": thumbnail_url}
    if theme_color:
        resp["theme_color"] = theme_color
    return resp


@app.get("/manifest.webmanifest")
async def manifest(db: AsyncSession = Depends(get_db)):
    from fastapi.responses import JSONResponse

    from app.services.server_settings_service import get_setting

    name = await get_setting(db, "server_name") or "Nekonoverse"
    icon_url = await get_setting(db, "server_icon_url")
    theme_color = await get_setting(db, "server_theme_color") or "#f5e6f0"

    if icon_url:
        icons = [
            {"src": icon_url, "sizes": "192x192", "type": "image/png"},
            {"src": icon_url, "sizes": "512x512", "type": "image/png"},
            {
                "src": icon_url,
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
app.include_router(accounts_router)
app.include_router(relationships_router)
app.include_router(notifications_router)
app.include_router(bookmarks_router)
app.include_router(polls_router)
app.include_router(statuses_router)
app.include_router(timelines_router)
app.include_router(streaming_router)
app.include_router(oauth_router)
app.include_router(passkey_router)
app.include_router(media_proxy_router)
app.include_router(media_router)
app.include_router(admin_router)
app.include_router(invites_router)
app.include_router(webfinger_router)
app.include_router(nodeinfo_router)
app.include_router(ap_router)
