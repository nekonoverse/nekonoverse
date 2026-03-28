"""ユーザーデータエクスポート用のValkeyベースジョブキュー。

email_queue.py と同じパターンに従う。
"""

import asyncio
import json
import logging
import time

from app.valkey_client import valkey as valkey_client

logger = logging.getLogger(__name__)

QUEUE_KEY = "export:queue"
DELAYED_KEY = "export:delayed"
DEAD_KEY = "export:dead"
HEARTBEAT_KEY = "worker:export:heartbeat"

MAX_ATTEMPTS = 3
MAX_CONCURRENT = 1


async def enqueue_export(export_id: str) -> None:
    """データエクスポートジョブをキューに追加する。"""
    job = {
        "export_id": export_id,
        "attempts": 0,
        "created_at": time.time(),
    }
    await valkey_client.lpush(QUEUE_KEY, json.dumps(job))
    logger.info("Enqueued data export %s", export_id)


async def _process_job(job: dict) -> None:
    """単一のエクスポートジョブを処理する。"""
    from uuid import UUID

    from sqlalchemy import select

    from app.database import async_session
    from app.models.data_export import DataExport

    export_id = UUID(job["export_id"])

    async with async_session() as db:
        result = await db.execute(
            select(DataExport).where(DataExport.id == export_id)
        )
        export = result.scalar_one_or_none()
        if not export:
            logger.warning("Export %s not found, skipping", export_id)
            return

        if export.status not in ("pending", "processing"):
            logger.info("Export %s already %s, skipping", export_id, export.status)
            return

        export.status = "processing"
        await db.commit()

        try:
            from app.services.export_service import generate_export

            await generate_export(db, export)
            await db.commit()
            logger.info("Export %s completed", export_id)
        except Exception as e:
            export.status = "failed"
            export.error = str(e)[:500]
            await db.commit()
            raise


async def _retry_or_dead(job: dict, error: str) -> None:
    """バックオフ付きで再キューするか、デッドレターに移動する。"""
    job["attempts"] = job.get("attempts", 0) + 1
    job["last_error"] = error

    if job["attempts"] >= MAX_ATTEMPTS:
        await valkey_client.lpush(DEAD_KEY, json.dumps(job))
        logger.warning(
            "Export job dead-lettered after %d attempts (id=%s): %s",
            job["attempts"], job.get("export_id"), error,
        )
    else:
        delay = min(30 * (2 ** job["attempts"]), 3600)
        run_at = time.time() + delay
        await valkey_client.zadd(DELAYED_KEY, {json.dumps(job): run_at})
        logger.info(
            "Export job retry #%d in %ds (id=%s): %s",
            job["attempts"], delay, job.get("export_id"), error,
        )


async def _promote_delayed() -> int:
    now = time.time()
    ready = await valkey_client.zrangebyscore(DELAYED_KEY, "-inf", str(now), start=0, num=10)
    if not ready:
        return 0
    for raw in ready:
        await valkey_client.lpush(QUEUE_KEY, raw)
    await valkey_client.zremrangebyscore(DELAYED_KEY, "-inf", str(now))
    return len(ready)


async def _update_heartbeat() -> None:
    try:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        await valkey_client.set(HEARTBEAT_KEY, now, ex=30)
    except Exception:
        pass


async def run_export_loop() -> None:
    """エクスポートワーカーのメインループ。"""
    logger.info("Export worker started (max_concurrent=%d)", MAX_CONCURRENT)
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def _run_one(raw: str) -> None:
        async with sem:
            try:
                job = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Invalid export job JSON: %s", raw[:200])
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
            logger.exception("Error in export worker loop")
            await asyncio.sleep(5)
