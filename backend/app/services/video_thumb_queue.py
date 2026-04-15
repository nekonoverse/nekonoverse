"""動画サムネイル生成用のValkeyベースジョブキュー。

外部の video-thumb マイクロサービスにリクエストし、生成されたサムネイルを
S3 に保存する。face_detect_queue.py と同じパターン。

ジョブ種別:
  - "local":  ローカルDriveFileのサムネイル生成 (drive_file_id指定)
  - "remote": リモートNoteAttachmentのサムネイル生成 (note_id + attachment_ids指定、将来拡張)
"""

import asyncio
import json
import logging
import time
import uuid

from app.config import settings
from app.valkey_client import valkey as valkey_client

logger = logging.getLogger(__name__)

QUEUE_KEY = "video_thumb:queue"
DELAYED_KEY = "video_thumb:delayed"  # sorted set: score=run_at_timestamp
DEAD_KEY = "video_thumb:dead"
HEARTBEAT_KEY = "worker:video_thumb:heartbeat"

MAX_ATTEMPTS = 5
MAX_CONCURRENT = 2  # 動画処理はCPU/メモリ集約的

_VIDEO_MIMES = {"video/mp4", "video/webm", "video/quicktime", "video/x-matroska"}


async def enqueue_local(drive_file_id: uuid.UUID) -> None:
    """ローカルDriveFileのサムネイル生成をキューに追加する。"""
    if not settings.video_thumb_enabled:
        return
    job = {
        "type": "local",
        "drive_file_id": str(drive_file_id),
        "attempts": 0,
        "created_at": time.time(),
    }
    await valkey_client.lpush(QUEUE_KEY, json.dumps(job))
    logger.debug("Enqueued local video-thumb job for %s", drive_file_id)


async def enqueue_remote(note_id: uuid.UUID, attachment_ids: list[uuid.UUID]) -> None:
    """リモートNoteAttachmentのサムネイル生成をキューに追加する (将来拡張)。"""
    if not settings.video_thumb_enabled:
        return
    job = {
        "type": "remote",
        "note_id": str(note_id),
        "attachment_ids": [str(a) for a in attachment_ids],
        "attempts": 0,
        "created_at": time.time(),
    }
    await valkey_client.lpush(QUEUE_KEY, json.dumps(job))
    logger.debug(
        "Enqueued remote video-thumb job for note %s (%d attachments)",
        note_id,
        len(attachment_ids),
    )


async def _process_local(job: dict) -> None:
    """ローカルDriveFileのサムネイル生成ジョブを処理する。"""
    from sqlalchemy import select

    from app.database import async_session
    from app.models.drive_file import DriveFile
    from app.storage import download_file, upload_file
    from app.utils.http_client import make_video_thumb_client

    drive_file_id = uuid.UUID(job["drive_file_id"])

    async with async_session() as db:
        result = await db.execute(select(DriveFile).where(DriveFile.id == drive_file_id))
        drive_file = result.scalar_one_or_none()
        if not drive_file:
            logger.warning("DriveFile %s not found, skipping", drive_file_id)
            return
        if drive_file.thumbnail_s3_key:
            logger.debug("DriveFile %s already has thumbnail, skipping", drive_file_id)
            return
        if drive_file.mime_type not in _VIDEO_MIMES:
            logger.debug(
                "DriveFile %s is not a video (%s), skipping",
                drive_file_id, drive_file.mime_type,
            )
            return

        # S3 から動画をダウンロード
        video_data = await download_file(drive_file.s3_key)

        # video-thumb サービスにリクエスト
        base = settings.video_thumb_base_url
        url = f"{base}/thumbnail" if not base.endswith("/thumbnail") else base

        async with make_video_thumb_client() as client:
            resp = await client.post(
                url,
                files={"file": ("video", video_data, drive_file.mime_type)},
            )
            resp.raise_for_status()

        thumb_data = resp.content
        thumb_mime = resp.headers.get("content-type", "image/webp").split(";")[0].strip()
        _ALLOWED_THUMB_MIMES = {"image/webp", "image/jpeg", "image/png"}
        if thumb_mime not in _ALLOWED_THUMB_MIMES:
            thumb_mime = "image/webp"
        duration = resp.headers.get("x-video-duration")
        width = resp.headers.get("x-video-width")
        height = resp.headers.get("x-video-height")

        # サムネイルを S3 にアップロード
        thumb_key = f"thumb/{drive_file.s3_key}.webp"
        await upload_file(thumb_key, thumb_data, thumb_mime)

        # DB 更新
        drive_file.thumbnail_s3_key = thumb_key
        drive_file.thumbnail_mime_type = thumb_mime
        if duration:
            try:
                drive_file.duration = float(duration)
            except ValueError:
                pass
        if width and not drive_file.width:
            try:
                drive_file.width = int(width)
            except ValueError:
                pass
        if height and not drive_file.height:
            try:
                drive_file.height = int(height)
            except ValueError:
                pass

        await db.commit()
        logger.info("Generated thumbnail for DriveFile %s -> %s", drive_file_id, thumb_key)


async def _process_remote(job: dict) -> None:
    """リモートNoteAttachmentのサムネイル生成ジョブを処理する (将来拡張)。

    現在はリモート動画のフルダウンロード→サムネ生成は未実装。
    AP の icon/preview からのサムネURL抽出は note_service.py で行う。
    """
    logger.debug("Remote video-thumb processing not yet implemented, skipping")


async def _process_job(job: dict) -> None:
    """単一のジョブをルーティングして処理する。"""
    job_type = job.get("type")
    if job_type == "local":
        await _process_local(job)
    elif job_type == "remote":
        await _process_remote(job)
    else:
        logger.warning("Unknown video-thumb job type: %s", job_type)


async def _retry_or_dead(job: dict, error: str) -> None:
    """バックオフ付きで再キューするか、デッドレターに移動する。"""
    job["attempts"] = job.get("attempts", 0) + 1
    job["last_error"] = error

    if job["attempts"] >= MAX_ATTEMPTS:
        await valkey_client.lpush(DEAD_KEY, json.dumps(job))
        logger.warning(
            "Video-thumb job dead-lettered after %d attempts: %s", job["attempts"], error
        )
    else:
        import random

        base_delay = min(30 * (2 ** job["attempts"]), 3600)
        delay = base_delay * (0.5 + random.random())
        run_at = time.time() + delay
        await valkey_client.zadd(DELAYED_KEY, {json.dumps(job): run_at})
        logger.info("Video-thumb job retry #%d in %ds: %s", job["attempts"], delay, error)


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
    """video-thumbワーカーのハートビートを更新する。"""
    try:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        await valkey_client.set(HEARTBEAT_KEY, now, ex=30)
    except Exception:
        pass


async def run_video_thumb_loop() -> None:
    """video-thumbワーカーのメインループ。"""
    if not settings.video_thumb_enabled:
        logger.info("VIDEO_THUMB_URL/UDS not set, video-thumb worker idle")
        while True:
            await asyncio.sleep(30)

    logger.info("Video-thumb worker started (max_concurrent=%d)", MAX_CONCURRENT)
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def _run_one(raw: str) -> None:
        async with sem:
            try:
                job = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Invalid video-thumb job JSON (length=%d)", len(raw))
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
            logger.exception("Error in video-thumb worker loop")
            await asyncio.sleep(5)
