"""neko-searchインデックス用のValkeyベースジョブキュー。

ジョブはJSON形式でValkeyリストに保存される。ワーカーがジョブをポップし、
neko-search外部サービスを呼び出してドキュメントのインデックス/削除を行う。

ジョブ種別:
  - "index":  ノートをインデックスに追加 (note_id, text, published)
  - "delete": ノートをインデックスから削除 (note_id)
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
    """neko-searchでのインデックス登録用にノートをキューに追加する。"""
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
    """neko-searchインデックスからのノート削除をキューに追加する。"""
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
    """neko-searchにPOST /indexを送信する。"""
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
    """neko-searchからDELETE /index/{note_id}を送信する。"""
    from app.utils.http_client import make_neko_search_client

    base = settings.neko_search_base_url.rstrip("/")
    async with make_neko_search_client() as client:
        resp = await client.delete(f"{base}/index/{job['note_id']}")
        resp.raise_for_status()


async def _process_job(job: dict) -> None:
    """単一のジョブをルーティングして処理する。"""
    job_type = job.get("type")
    if job_type == "index":
        await _process_index(job)
    elif job_type == "delete":
        await _process_delete(job)
    else:
        logger.warning("Unknown neko-search job type: %s", job_type)


async def _retry_or_dead(job: dict, error: str) -> None:
    """バックオフ付きで再キューするか、デッドレターに移動する。"""
    job["attempts"] = job.get("attempts", 0) + 1
    job["last_error"] = error

    if job["attempts"] >= MAX_ATTEMPTS:
        await valkey_client.lpush(DEAD_KEY, json.dumps(job))
        logger.warning(
            "neko-search job dead-lettered after %d attempts: %s", job["attempts"], error
        )
    else:
        import random

        # L-3: ジッタを追加してthundering herdを防止
        base_delay = min(30 * (2 ** job["attempts"]), 3600)
        delay = base_delay * (0.5 + random.random())
        run_at = time.time() + delay
        await valkey_client.zadd(DELAYED_KEY, {json.dumps(job): run_at})
        logger.info("neko-search job retry #%d in %ds: %s", job["attempts"], delay, error)


async def _promote_delayed() -> int:
    """run_atが経過した遅延ジョブをメインキューに戻す。"""
    now = time.time()
    ready = await valkey_client.zrangebyscore(DELAYED_KEY, "-inf", str(now), start=0, num=50)
    if not ready:
        return 0
    for raw in ready:
        await valkey_client.lpush(QUEUE_KEY, raw)
    await valkey_client.zremrangebyscore(DELAYED_KEY, "-inf", str(now))
    return len(ready)


async def _update_heartbeat() -> None:
    """neko-searchワーカーのハートビートを更新する。"""
    try:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        await valkey_client.set(HEARTBEAT_KEY, now, ex=30)
    except Exception:
        pass


async def run_search_index_loop() -> None:
    """neko-searchワーカーのメインループ。"""
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
                # L-5: 生データではなく長さのみログ出力
                logger.warning("Invalid neko-search job JSON (length=%d)", len(raw))
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
