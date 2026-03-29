"""Activity 配送ワーカー -- 配送キューを処理する。"""

import asyncio
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

MAX_CONCURRENT = 16

# L-1: 署名鍵キャッシュ (actor_id -> (Actor, private_key_pem, cached_at))
_signing_key_cache: dict[uuid.UUID, tuple[Actor, str, float]] = {}
_SIGNING_KEY_CACHE_TTL = 3600  # 1 hour

# ワーカー用の共有HTTPクライアント
_http_client: httpx.AsyncClient | None = None


def _get_http_client(settings) -> httpx.AsyncClient:
    """配送ワーカー用の共有 HTTP クライアントを取得または作成する。"""
    global _http_client
    if _http_client is None:
        from app.utils.http_client import make_async_client

        _http_client = make_async_client(
            timeout=30.0,
            verify=not settings.skip_ssl_verify,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
        )
    return _http_client


async def get_pending_jobs(
    db: AsyncSession, limit: int = MAX_CONCURRENT
) -> list[DeliveryJob]:
    """行レベルロック付きで配送待ちジョブを取得する。"""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(DeliveryJob)
        .where(
            DeliveryJob.status == "pending",
            (DeliveryJob.next_retry_at.is_(None)) | (DeliveryJob.next_retry_at <= now),
        )
        .order_by(DeliveryJob.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(result.scalars().all())


async def get_next_jobs(db: AsyncSession, limit: int = 20) -> list[DeliveryJob]:
    """H-1: Get multiple deliverable jobs for concurrent processing."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(DeliveryJob)
        .where(
            DeliveryJob.status == "pending",
            (DeliveryJob.next_retry_at.is_(None)) | (DeliveryJob.next_retry_at <= now),
        )
        .order_by(DeliveryJob.created_at)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_actor_with_key(db: AsyncSession, actor_id: uuid.UUID) -> tuple[Actor | None, str]:
    """署名用にアクターとその秘密鍵を取得する。インメモリキャッシュを使用。"""
    import time

    cached = _signing_key_cache.get(actor_id)
    if cached:
        actor, pem, cached_at = cached
        if time.time() - cached_at < _SIGNING_KEY_CACHE_TTL:
            return actor, pem

    result = await db.execute(
        select(Actor).options(selectinload(Actor.local_user)).where(Actor.id == actor_id)
    )
    actor = result.scalar_one_or_none()
    if not actor or not actor.local_user:
        return actor, ""

    _signing_key_cache[actor_id] = (actor, actor.local_user.private_key_pem, time.time())
    return actor, actor.local_user.private_key_pem


async def deliver_activity(job: DeliveryJob, actor: Actor, private_key_pem: str) -> bool:
    """activity をリモート Inbox に配送する。"""
    from app.config import settings as app_settings
    from app.utils.network import is_private_host

    # SSRF防止: 内部ネットワークへの配送をブロック
    from urllib.parse import urlparse

    parsed = urlparse(job.target_inbox_url)
    if not app_settings.allow_private_networks and is_private_host(parsed.hostname or ""):
        logger.warning("Blocked delivery to private host: %s", job.target_inbox_url)
        return False

    body = json.dumps(job.payload).encode("utf-8")
    # 正しいスキームを保証するためローカルアクターの動的 URL を使用
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


async def _deliver_one(job_id: uuid.UUID, sem: asyncio.Semaphore) -> None:
    """セマフォベースの同時実行制御で単一ジョブを配送する。"""
    async with sem:
        async with async_session() as db:
            job = await db.get(DeliveryJob, job_id)
            if not job or job.status != "processing":
                return

            actor, private_key_pem = await get_actor_with_key(db, job.actor_id)
            if not actor or not private_key_pem:
                job.status = "dead"
                job.error_message = "Actor or private key not found"
                await db.commit()
                return

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


async def _update_heartbeat():
    """Valkey でワーカーのハートビートを更新する。"""
    try:
        now = datetime.now(timezone.utc).isoformat()
        await valkey_client.set("worker:heartbeat", now, ex=30)
    except Exception:
        pass


async def run_delivery_loop():
    """並行ジョブ処理を行うメイン配送ワーカーループ。"""
    logger.info("Delivery worker started (max_concurrent=%d)", MAX_CONCURRENT)

    sem = asyncio.Semaphore(MAX_CONCURRENT)
    tasks: set[asyncio.Task] = set()

    while True:
        try:
            await _update_heartbeat()

            had_work = False
            async with async_session() as db:
                jobs = await get_pending_jobs(db, limit=MAX_CONCURRENT)
                if jobs:
                    had_work = True
                    now = datetime.now(timezone.utc)
                    for job in jobs:
                        job.status = "processing"
                        job.last_attempted_at = now
                        job.attempts += 1
                    await db.commit()

                    for job in jobs:
                        task = asyncio.create_task(_deliver_one(job.id, sem))
                        tasks.add(task)
                        task.add_done_callback(tasks.discard)

            if not had_work:
                # Valkey からの通知を待機
                await valkey_client.brpop("delivery:queue", timeout=5)
                # 結果は破棄 -- ウェイクアップシグナルとして使用するだけ

        except Exception:
            logger.exception("Error in delivery worker loop")
            await asyncio.sleep(5)
