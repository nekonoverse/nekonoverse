"""Activity delivery worker -- processes the delivery queue."""

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.activitypub.http_signature import sign_request
from app.database import async_session
from app.models.actor import Actor
from app.models.delivery import DeliveryJob
from app.valkey_client import valkey as valkey_client

logger = logging.getLogger(__name__)

AP_CONTENT_TYPE = 'application/ld+json; profile="https://www.w3.org/ns/activitystreams"'

# 署名鍵キャッシュ (actor_id -> (Actor, private_key_pem))
_signing_key_cache: dict[uuid.UUID, tuple[Actor, str]] = {}

# ワーカー用の共有HTTPクライアント
_http_client: httpx.AsyncClient | None = None


def _get_http_client(settings) -> httpx.AsyncClient:
    """Get or create a shared HTTP client for the delivery worker."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=30.0,
            verify=not settings.skip_ssl_verify,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
        )
    return _http_client


async def get_next_job(db: AsyncSession) -> DeliveryJob | None:
    """Get the next deliverable job from the queue."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(DeliveryJob)
        .where(
            DeliveryJob.status == "pending",
            (DeliveryJob.next_retry_at.is_(None)) | (DeliveryJob.next_retry_at <= now),
        )
        .order_by(DeliveryJob.created_at)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_actor_with_key(db: AsyncSession, actor_id: uuid.UUID) -> tuple[Actor | None, str]:
    """Get actor and its private key for signing. Uses in-memory cache."""
    cached = _signing_key_cache.get(actor_id)
    if cached:
        return cached

    result = await db.execute(
        select(Actor).options(selectinload(Actor.local_user)).where(Actor.id == actor_id)
    )
    actor = result.scalar_one_or_none()
    if not actor or not actor.local_user:
        return actor, ""

    pair = (actor, actor.local_user.private_key_pem)
    _signing_key_cache[actor_id] = pair
    return pair


async def deliver_activity(job: DeliveryJob, actor: Actor, private_key_pem: str) -> bool:
    """Deliver an activity to a remote inbox."""
    from app.config import settings as app_settings

    body = json.dumps(job.payload).encode("utf-8")
    # Use dynamic URL for local actor to ensure correct scheme
    if actor.domain is None:
        key_id = f"{app_settings.server_url}/users/{actor.username}#main-key"
    else:
        key_id = f"{actor.ap_id}#main-key"

    headers = sign_request(
        private_key_pem=private_key_pem,
        key_id=key_id,
        method="POST",
        url=job.target_inbox_url,
        body=body,
    )
    headers["Content-Type"] = AP_CONTENT_TYPE

    from app.config import settings

    resp = await _get_http_client(settings).post(
        job.target_inbox_url,
        content=body,
        headers=headers,
    )
    return resp.status_code in (200, 202, 204)


async def process_jobs():
    """Process delivery jobs from the queue."""
    async with async_session() as db:
        job = await get_next_job(db)
        if not job:
            return False

        job.status = "processing"
        job.last_attempted_at = datetime.now(timezone.utc)
        job.attempts += 1
        await db.commit()

        actor, private_key_pem = await get_actor_with_key(db, job.actor_id)
        if not actor or not private_key_pem:
            job.status = "dead"
            job.error_message = "Actor or private key not found"
            await db.commit()
            return True

        try:
            success = await deliver_activity(job, actor, private_key_pem)
            if success:
                job.status = "delivered"
                logger.info("Delivered to %s", job.target_inbox_url)
            else:
                raise Exception("Non-success status code")
        except Exception as e:
            logger.warning(
                "Delivery failed to %s (attempt %d/%d): %s",
                job.target_inbox_url,
                job.attempts,
                job.max_attempts,
                str(e),
            )
            if job.attempts >= job.max_attempts:
                job.status = "dead"
            else:
                job.status = "pending"
                delay = min(60 * (2**job.attempts), 21600)  # Max 6 hours
                job.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            job.error_message = str(e)

        await db.commit()
        return True


async def _update_heartbeat():
    """Update worker heartbeat in Valkey."""
    try:
        now = datetime.now(timezone.utc).isoformat()
        await valkey_client.set("worker:heartbeat", now, ex=30)
    except Exception:
        pass


async def run_delivery_loop():
    """Main delivery worker loop."""
    logger.info("Delivery worker started")

    while True:
        try:
            await _update_heartbeat()
            had_work = await process_jobs()
            if not had_work:
                # Wait for notification from Valkey
                await valkey_client.brpop("delivery:queue", timeout=5)
                # result is discarded -- we just use it as a wake-up signal
        except Exception:
            logger.exception("Error in delivery worker loop")
            import asyncio

            await asyncio.sleep(5)
