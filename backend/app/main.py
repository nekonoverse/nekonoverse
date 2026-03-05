from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.activitypub.nodeinfo import router as nodeinfo_router
from app.activitypub.routes import router as ap_router
from app.activitypub.webfinger import router as webfinger_router
from app.api.auth import router as auth_router
from app.api.mastodon.accounts import router as accounts_router
from app.api.mastodon.statuses import router as statuses_router
from app.api.mastodon.timelines import router as timelines_router
from app.api.oauth import router as oauth_router
from app.api.admin import router as admin_router
from app.api.media import router as media_router
from app.api.passkey import router as passkey_router
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging
    from app.storage import ensure_bucket
    try:
        await ensure_bucket()
    except Exception as e:
        logging.getLogger(__name__).warning("Could not ensure S3 bucket: %s", e)
    yield


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
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/instance")
async def instance_info():
    thumbnail_url = None
    try:
        from app.valkey_client import valkey
        icon_url = await valkey.get("server:icon_url")
        if icon_url:
            thumbnail_url = icon_url
    except Exception:
        pass

    resp: dict = {
        "uri": settings.domain,
        "title": "Nekonoverse",
        "description": "A cat-friendly ActivityPub server",
        "version": "0.1.0",
        "urls": {},
        "stats": {"user_count": 0, "status_count": 0, "domain_count": 0},
        "registrations": settings.registration_open,
    }
    if thumbnail_url:
        resp["thumbnail"] = {"url": thumbnail_url}
    return resp


@app.get("/api/v1/health")
async def health():
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(accounts_router)
app.include_router(statuses_router)
app.include_router(timelines_router)
app.include_router(oauth_router)
app.include_router(passkey_router)
app.include_router(media_router)
app.include_router(admin_router)
app.include_router(webfinger_router)
app.include_router(nodeinfo_router)
app.include_router(ap_router)
