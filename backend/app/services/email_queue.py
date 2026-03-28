"""メール配信用のValkeyベースジョブキュー。

face_detect_queue.py と同じパターンに従う:
- メインキュー (Valkey リスト)
- 遅延キュー (Valkey ソート済みセット) 指数バックオフ付きリトライ用
- デッドレターキュー 恒久的に失敗したジョブ用
"""

import asyncio
import json
import logging
import time

from app.config import settings
from app.valkey_client import valkey as valkey_client

logger = logging.getLogger(__name__)

QUEUE_KEY = "email:queue"
DELAYED_KEY = "email:delayed"
DEAD_KEY = "email:dead"
HEARTBEAT_KEY = "worker:email:heartbeat"

MAX_ATTEMPTS = 5
MAX_CONCURRENT = 2


async def enqueue_email(to: str, subject: str, html: str, text: str) -> None:
    """配信用にメールをキューに追加する。"""
    job = {
        "to": to,
        "subject": subject,
        "html": html,
        "text": text,
        "attempts": 0,
        "created_at": time.time(),
    }
    await valkey_client.lpush(QUEUE_KEY, json.dumps(job))
    logger.debug("Enqueued email to %s: %s", to, subject)


async def _process_job(job: dict) -> None:
    """単一のメールを送信する。"""
    from app.services.email_service import send_email

    await send_email(
        to=job["to"],
        subject=job["subject"],
        html=job["html"],
        text=job["text"],
    )
    logger.info("Email sent to %s: %s", job["to"], job["subject"])


async def _retry_or_dead(job: dict, error: str) -> None:
    """バックオフ付きで再キューするか、デッドレターに移動する。"""
    job["attempts"] = job.get("attempts", 0) + 1
    job["last_error"] = error

    if job["attempts"] >= MAX_ATTEMPTS:
        await valkey_client.lpush(DEAD_KEY, json.dumps(job))
        logger.warning(
            "Email job dead-lettered after %d attempts (to=%s): %s",
            job["attempts"], job.get("to"), error,
        )
    else:
        delay = min(30 * (2 ** job["attempts"]), 3600)
        run_at = time.time() + delay
        await valkey_client.zadd(DELAYED_KEY, {json.dumps(job): run_at})
        logger.info(
            "Email job retry #%d in %ds (to=%s): %s",
            job["attempts"], delay, job.get("to"), error,
        )


async def _promote_delayed() -> int:
    """run_at が経過した遅延ジョブをメインキューに戻す。"""
    now = time.time()
    ready = await valkey_client.zrangebyscore(DELAYED_KEY, "-inf", str(now), start=0, num=50)
    if not ready:
        return 0
    for raw in ready:
        await valkey_client.lpush(QUEUE_KEY, raw)
    await valkey_client.zremrangebyscore(DELAYED_KEY, "-inf", str(now))
    return len(ready)


async def _update_heartbeat() -> None:
    """メールワーカーのハートビートを更新する。"""
    try:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        await valkey_client.set(HEARTBEAT_KEY, now, ex=30)
    except Exception:
        pass


async def run_email_loop() -> None:
    """メールワーカーのメインループ。"""
    if not settings.email_enabled:
        logger.info("SMTP not configured, email worker idle")
        while True:
            await asyncio.sleep(30)

    logger.info("Email worker started (max_concurrent=%d)", MAX_CONCURRENT)
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def _run_one(raw: str) -> None:
        async with sem:
            try:
                job = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Invalid email job JSON: %s", raw[:200])
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
            logger.exception("Error in email worker loop")
            await asyncio.sleep(5)
