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
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown


app = FastAPI(
    title="Nekonoverse",
    version="0.1.0",
    description="ActivityPub server with Misskey-compatible emoji reactions",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[f"http://localhost:3000", settings.server_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/instance")
async def instance_info():
    return {
        "uri": settings.domain,
        "title": "Nekonoverse",
        "description": "A cat-friendly ActivityPub server",
        "version": "0.1.0",
        "urls": {},
        "stats": {"user_count": 0, "status_count": 0, "domain_count": 0},
        "registrations": True,
    }


@app.get("/api/v1/health")
async def health():
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(accounts_router)
app.include_router(statuses_router)
app.include_router(timelines_router)
app.include_router(oauth_router)
app.include_router(webfinger_router)
app.include_router(nodeinfo_router)
app.include_router(ap_router)
