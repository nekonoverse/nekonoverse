"""neko-vision画像タグ付け用のValkeyベースジョブキュー。

face_detect_queue.py と同じパターン。バージョン管理は行わず、
再判定はCLI (scripts/vision_retag.py) で日時指定で行う。

ジョブ種別:
  - "local":  ローカルDriveFileのタグ付け (drive_file_id + note_text + context)
  - "remote": リモートNoteAttachmentのタグ付け (note_id + attachment_ids + note_text + context)
"""

import asyncio
import json
import logging
import time
import uuid

from app.config import settings
from app.valkey_client import valkey as valkey_client

logger = logging.getLogger(__name__)

QUEUE_KEY = "neko_vision:queue"
DELAYED_KEY = "neko_vision:delayed"
DEAD_KEY = "neko_vision:dead"
HEARTBEAT_KEY = "worker:neko_vision:heartbeat"

MAX_ATTEMPTS = 5
MAX_CONCURRENT = 2  # Ollamaはシリアル推論のため少なめ


async def enqueue_local(
    drive_file_id: uuid.UUID,
    note_id: uuid.UUID,
    *,
    note_text: str | None = None,
    context: list[str] | None = None,
) -> None:
    """ローカルDriveFileのタグ付けをキューに追加する。"""
    if not settings.neko_vision_enabled:
        return
    job: dict = {
        "type": "local",
        "drive_file_id": str(drive_file_id),
        "note_id": str(note_id),
        "attempts": 0,
        "created_at": time.time(),
    }
    if note_text:
        job["note_text"] = note_text[:1000]
    if context:
        job["context"] = context[:5]
    await valkey_client.lpush(QUEUE_KEY, json.dumps(job))
    logger.debug("Enqueued local vision job for %s", drive_file_id)


async def enqueue_remote(
    note_id: uuid.UUID,
    attachment_ids: list[uuid.UUID],
    *,
    note_text: str | None = None,
    context: list[str] | None = None,
) -> None:
    """リモートNoteAttachmentのタグ付けをキューに追加する。"""
    if not settings.neko_vision_enabled:
        return
    job: dict = {
        "type": "remote",
        "note_id": str(note_id),
        "attachment_ids": [str(a) for a in attachment_ids],
        "attempts": 0,
        "created_at": time.time(),
    }
    if note_text:
        job["note_text"] = note_text[:1000]
    if context:
        job["context"] = context[:5]
    await valkey_client.lpush(QUEUE_KEY, json.dumps(job))
    logger.debug(
        "Enqueued remote vision job for note %s (%d attachments)",
        note_id,
        len(attachment_ids),
    )


async def _process_local(job: dict) -> None:
    """ローカルDriveFileのタグ付けジョブを処理する。"""
    from sqlalchemy import select

    from app.database import async_session
    from app.models.drive_file import DriveFile
    from app.services.vision_service import auto_tag_image

    drive_file_id = uuid.UUID(job["drive_file_id"])

    async with async_session() as db:
        result = await db.execute(select(DriveFile).where(DriveFile.id == drive_file_id))
        drive_file = result.scalar_one_or_none()
        if not drive_file:
            logger.warning("DriveFile %s not found, skipping vision job", drive_file_id)
            return

        # 既にタグ付け済みの場合はスキップ
        if drive_file.vision_at is not None:
            logger.debug("DriveFile %s already tagged, skipping", drive_file_id)
            return

        await auto_tag_image(
            db,
            drive_file,
            note_text=job.get("note_text"),
            context=job.get("context"),
        )


async def _process_remote(job: dict) -> None:
    """リモートNoteAttachmentのタグ付けジョブを処理する。"""
    from app.services.vision_service import tag_remote_attachments

    note_id = uuid.UUID(job["note_id"])
    attachment_ids = [uuid.UUID(a) for a in job["attachment_ids"]]
    await tag_remote_attachments(
        note_id,
        attachment_ids,
        note_text=job.get("note_text"),
        context=job.get("context"),
    )


async def _process_job(job: dict) -> None:
    """単一のジョブをルーティングして処理する。"""
    job_type = job.get("type")
    if job_type == "local":
        await _process_local(job)
    elif job_type == "remote":
        await _process_remote(job)
    else:
        logger.warning("Unknown vision job type: %s", job_type)


async def _retry_or_dead(job: dict, error: str) -> None:
    """バックオフ付きで再キューするか、デッドレターに移動する。"""
    job["attempts"] = job.get("attempts", 0) + 1
    job["last_error"] = error

    if job["attempts"] >= MAX_ATTEMPTS:
        await valkey_client.lpush(DEAD_KEY, json.dumps(job))
        logger.warning(
            "Vision job dead-lettered after %d attempts: %s", job["attempts"], error
        )
    else:
        import random

        base_delay = min(30 * (2 ** job["attempts"]), 3600)
        delay = base_delay * (0.5 + random.random())
        run_at = time.time() + delay
        await valkey_client.zadd(DELAYED_KEY, {json.dumps(job): run_at})
        logger.info("Vision job retry #%d in %ds: %s", job["attempts"], delay, error)


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
    """neko-visionワーカーのハートビートを更新する。"""
    try:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        await valkey_client.set(HEARTBEAT_KEY, now, ex=30)
    except Exception:
        pass


async def run_vision_loop() -> None:
    """neko-visionワーカーのメインループ。"""
    if not settings.neko_vision_enabled:
        logger.info("NEKO_VISION_URL/UDS not set, neko-vision worker idle")
        while True:
            await asyncio.sleep(30)

    logger.info("Vision worker started (max_concurrent=%d)", MAX_CONCURRENT)

    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def _run_one(raw: str) -> None:
        async with sem:
            try:
                job = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Invalid vision job JSON (length=%d)", len(raw))
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
            logger.exception("Error in vision worker loop")
            await asyncio.sleep(5)
