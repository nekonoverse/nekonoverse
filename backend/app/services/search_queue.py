"""Valkey-based job queue for neko-search indexing.

Jobs are stored as JSON in a Valkey list. The worker pops jobs, calls the
neko-search external service to index/delete documents.

Job types:
  - "index":  index a note (note_id, text, published)
  - "delete": remove a note from the index (note_id)
"""

import asyncio
import json
import logging
import time
import uuid

from app.config import settings
from app.valkey_client import valkey as valkey_client

logger = logging.getLogger(__name__)

QUEUE_KEY = "neko_search:queue"
DELAYED_KEY = "neko_search:delayed"
DEAD_KEY = "neko_search:dead"
HEARTBEAT_KEY = "worker:neko_search:heartbeat"

MAX_ATTEMPTS = 3
MAX_CONCURRENT = 8


async def enqueue_index(note_id: uuid.UUID, text: str, published) -> None:
    """Enqueue a note for indexing in neko-search."""
    if not settings.neko_search_enabled:
        return
    pub = published.isoformat() if hasattr(published, "isoformat") else str(published)
    job = {
        "type": "index",
        "note_id": str(note_id),
        "text": text,
        "published": pub,
        "attempts": 0,
        "created_at": time.time(),
    }
    await valkey_client.lpush(QUEUE_KEY, json.dumps(job))
    logger.debug("Enqueued search index job for %s", note_id)


async def enqueue_delete(note_id: uuid.UUID) -> None:
    """Enqueue a note deletion from neko-search index."""
    if not settings.neko_search_enabled:
        return
    job = {
        "type": "delete",
        "note_id": str(note_id),
        "attempts": 0,
        "created_at": time.time(),
    }
    await valkey_client.lpush(QUEUE_KEY, json.dumps(job))
    logger.debug("Enqueued search delete job for %s", note_id)


async def _process_index(job: dict) -> None:
    """POST /index to neko-search."""
    from app.utils.http_client import make_neko_search_client

    base = settings.neko_search_base_url.rstrip("/")
    async with make_neko_search_client() as client:
        resp = await client.post(
            f"{base}/index",
            json={
                "note_id": job["note_id"],
                "text": job["text"],
                "published": job.get("published"),
            },
        )
        resp.raise_for_status()


async def _process_delete(job: dict) -> None:
    """DELETE /index/{note_id} from neko-search."""
    from app.utils.http_client import make_neko_search_client

    base = settings.neko_search_base_url.rstrip("/")
    async with make_neko_search_client() as client:
        resp = await client.delete(f"{base}/index/{job['note_id']}")
        resp.raise_for_status()


async def _process_job(job: dict) -> None:
    """Route and process a single job."""
    job_type = job.get("type")
    if job_type == "index":
        await _process_index(job)
    elif job_type == "delete":
        await _process_delete(job)
    else:
        logger.warning("Unknown neko-search job type: %s", job_type)


async def _retry_or_dead(job: dict, error: str) -> None:
    """Re-enqueue with backoff or move to dead-letter."""
    job["attempts"] = job.get("attempts", 0) + 1
    job["last_error"] = error

    if job["attempts"] >= MAX_ATTEMPTS:
        await valkey_client.lpush(DEAD_KEY, json.dumps(job))
        logger.warning("neko-search job dead-lettered after %d attempts: %s",
                       job["attempts"], error)
    else:
        delay = min(30 * (2 ** job["attempts"]), 3600)
        run_at = time.time() + delay
        await valkey_client.zadd(DELAYED_KEY, {json.dumps(job): run_at})
        logger.info("neko-search job retry #%d in %ds: %s",
                    job["attempts"], delay, error)


async def _promote_delayed() -> int:
    """Move delayed jobs whose run_at has passed back to the main queue."""
    now = time.time()
    ready = await valkey_client.zrangebyscore(DELAYED_KEY, "-inf", str(now), start=0, num=50)
    if not ready:
        return 0
    for raw in ready:
        await valkey_client.lpush(QUEUE_KEY, raw)
    await valkey_client.zremrangebyscore(DELAYED_KEY, "-inf", str(now))
    return len(ready)


async def _update_heartbeat() -> None:
    """Update neko-search worker heartbeat."""
    try:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        await valkey_client.set(HEARTBEAT_KEY, now, ex=30)
    except Exception:
        pass


async def run_search_index_loop() -> None:
    """Main neko-search worker loop."""
    if not settings.neko_search_enabled:
        logger.info("NEKO_SEARCH_URL/UDS not set, neko-search worker idle")
        while True:
            await asyncio.sleep(30)

    logger.info("neko-search worker started (max_concurrent=%d)", MAX_CONCURRENT)
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def _run_one(raw: str) -> None:
        async with sem:
            try:
                job = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Invalid neko-search job JSON: %s", raw[:200])
                return
            try:
                await _process_job(job)
            except Exception as e:
                await _retry_or_dead(job, str(e))

    tasks: set[asyncio.Task] = set()

    while True:
        try:
            await _update_heartbeat()
            await _promote_delayed()

            result = await valkey_client.brpop(QUEUE_KEY, timeout=3)
            if result:
                _, raw = result
                task = asyncio.create_task(_run_one(raw))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
        except Exception:
            logger.exception("Error in neko-search worker loop")
            await asyncio.sleep(5)
