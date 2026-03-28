"""face-detectフォーカルポイント検出用のValkeyベースジョブキュー。

ジョブはJSON形式でValkeyリストに保存される。ワーカーがジョブをポップし、処理する。
失敗時は指数バックオフ付きで再エンキューする (最大max_attempts回)。
永続的に失敗したジョブはデッドレターリストに移動する。

ジョブ種別:
  - "local":  ローカルDriveFileのフォーカルポイントを検出 (drive_file_id指定)
  - "remote": リモートNoteAttachmentのフォーカルポイントを検出 (note_id + attachment_ids指定)
"""

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict

from app.config import settings
from app.valkey_client import valkey as valkey_client

logger = logging.getLogger(__name__)

QUEUE_KEY = "face_detect:queue"
DELAYED_KEY = "face_detect:delayed"  # sorted set: score=run_at_timestamp
DEAD_KEY = "face_detect:dead"
HEARTBEAT_KEY = "worker:face_detect:heartbeat"
VERSION_KEY = "face_detect:version"

MAX_ATTEMPTS = 5
MAX_CONCURRENT = 4

_current_version: str | None = None


async def _fetch_version() -> str | None:
    """face-detectサービスから現在のバージョンを取得する。"""
    try:
        from app.utils.http_client import make_face_detect_client

        base = settings.face_detect_base_url
        # /object-detection → /version
        if base.endswith("/object-detection"):
            version_url = base.rsplit("/", 1)[0] + "/version"
        else:
            version_url = base.rstrip("/") + "/version"

        async with make_face_detect_client() as client:
            resp = await client.get(version_url)
            resp.raise_for_status()
            return resp.json().get("version")
    except Exception:
        logger.warning("Failed to fetch face-detect version", exc_info=True)
        return None


async def _requeue_outdated(version: str) -> int:
    """古いバージョンで検出された画像を再エンキューする。"""
    from sqlalchemy import select

    from app.database import async_session
    from app.models.drive_file import DriveFile
    from app.models.note_attachment import NoteAttachment

    count = 0
    async with async_session() as db:
        # 古いバージョンのローカルDriveFile
        rows = await db.execute(
            select(DriveFile.id).where(
                DriveFile.mime_type.like("image/%"),
                DriveFile.focal_detect_version.isnot(None),
                DriveFile.focal_detect_version != version,
                DriveFile.focal_detect_version != "manual",
            )
        )
        local_ids = [row[0] for row in rows.all()]
        for fid in local_ids:
            job = {
                "type": "local",
                "drive_file_id": str(fid),
                "attempts": 0,
                "created_at": time.time(),
                "detect_version": version,
            }
            await valkey_client.lpush(QUEUE_KEY, json.dumps(job))
            count += 1

        # 古いバージョンのリモートNoteAttachment (note_idごとにグループ化)
        rows = await db.execute(
            select(NoteAttachment.id, NoteAttachment.note_id).where(
                NoteAttachment.remote_url.isnot(None),
                NoteAttachment.focal_detect_version.isnot(None),
                NoteAttachment.focal_detect_version != version,
                NoteAttachment.focal_detect_version != "manual",
            )
        )
        by_note: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for att_id, note_id in rows.all():
            by_note[note_id].append(att_id)

        for note_id, att_ids in by_note.items():
            job = {
                "type": "remote",
                "note_id": str(note_id),
                "attachment_ids": [str(a) for a in att_ids],
                "attempts": 0,
                "created_at": time.time(),
                "detect_version": version,
            }
            await valkey_client.lpush(QUEUE_KEY, json.dumps(job))
            count += len(att_ids)

    return count


async def enqueue_local(drive_file_id: uuid.UUID) -> None:
    """ローカルDriveFileの顔検出をキューに追加する。"""
    if not settings.face_detect_enabled:
        return
    job = {
        "type": "local",
        "drive_file_id": str(drive_file_id),
        "attempts": 0,
        "created_at": time.time(),
        "detect_version": _current_version,
    }
    await valkey_client.lpush(QUEUE_KEY, json.dumps(job))
    logger.debug("Enqueued local face-detect job for %s", drive_file_id)


async def enqueue_remote(note_id: uuid.UUID, attachment_ids: list[uuid.UUID]) -> None:
    """リモートNoteAttachmentの顔検出をキューに追加する。"""
    if not settings.face_detect_enabled:
        return
    job = {
        "type": "remote",
        "note_id": str(note_id),
        "attachment_ids": [str(a) for a in attachment_ids],
        "attempts": 0,
        "created_at": time.time(),
        "detect_version": _current_version,
    }
    await valkey_client.lpush(QUEUE_KEY, json.dumps(job))
    logger.debug(
        "Enqueued remote face-detect job for note %s (%d attachments)", note_id, len(attachment_ids)
    )


async def _process_local(job: dict) -> None:
    """ローカルDriveFileの顔検出ジョブを処理する。"""
    from sqlalchemy import select

    from app.database import async_session
    from app.models.drive_file import DriveFile
    from app.services.drive_service import auto_detect_focal_point

    drive_file_id = uuid.UUID(job["drive_file_id"])
    detect_version = job.get("detect_version") or _current_version

    async with async_session() as db:
        result = await db.execute(select(DriveFile).where(DriveFile.id == drive_file_id))
        drive_file = result.scalar_one_or_none()
        if not drive_file:
            logger.warning("DriveFile %s not found, skipping", drive_file_id)
            return

        await auto_detect_focal_point(db, drive_file, detect_version=detect_version)


async def _process_remote(job: dict) -> None:
    """リモートNoteAttachmentの顔検出ジョブを処理する。"""
    from app.services.focal_point_service import detect_remote_focal_points

    note_id = uuid.UUID(job["note_id"])
    attachment_ids = [uuid.UUID(a) for a in job["attachment_ids"]]
    detect_version = job.get("detect_version") or _current_version
    await detect_remote_focal_points(note_id, attachment_ids, detect_version=detect_version)


async def _process_job(job: dict) -> None:
    """単一のジョブをルーティングして処理する。"""
    job_type = job.get("type")
    if job_type == "local":
        await _process_local(job)
    elif job_type == "remote":
        await _process_remote(job)
    else:
        logger.warning("Unknown face-detect job type: %s", job_type)


async def _retry_or_dead(job: dict, error: str) -> None:
    """バックオフ付きで再キューするか、デッドレターに移動する。"""
    job["attempts"] = job.get("attempts", 0) + 1
    job["last_error"] = error

    if job["attempts"] >= MAX_ATTEMPTS:
        await valkey_client.lpush(DEAD_KEY, json.dumps(job))
        logger.warning(
            "Face-detect job dead-lettered after %d attempts: %s", job["attempts"], error
        )
    else:
        import random

        # L-3: ジッタを追加してthundering herdを防止
        base_delay = min(30 * (2 ** job["attempts"]), 3600)  # 最大1時間
        delay = base_delay * (0.5 + random.random())
        run_at = time.time() + delay
        await valkey_client.zadd(DELAYED_KEY, {json.dumps(job): run_at})
        logger.info("Face-detect job retry #%d in %ds: %s", job["attempts"], delay, error)


async def _promote_delayed() -> int:
    """run_atが経過した遅延ジョブをメインキューに戻す。"""
    now = time.time()
    # 実行準備ができたジョブを取得
    ready = await valkey_client.zrangebyscore(DELAYED_KEY, "-inf", str(now), start=0, num=50)
    if not ready:
        return 0
    for raw in ready:
        await valkey_client.lpush(QUEUE_KEY, raw)
    await valkey_client.zremrangebyscore(DELAYED_KEY, "-inf", str(now))
    return len(ready)


async def _update_heartbeat() -> None:
    """face-detectワーカーのハートビートを更新する。"""
    try:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        await valkey_client.set(HEARTBEAT_KEY, now, ex=30)
    except Exception:
        pass


async def run_face_detect_loop() -> None:
    """face-detectワーカーのメインループ。

    Valkeyキューからジョブをポップし、並行数セマフォで処理し、
    指数バックオフ付きでリトライを処理する。
    """
    global _current_version

    if not settings.face_detect_enabled:
        logger.info("FACE_DETECT_URL/UDS not set, face-detect worker idle")
        while True:
            await asyncio.sleep(30)

    logger.info("Face-detect worker started (max_concurrent=%d)", MAX_CONCURRENT)

    # 現在のバージョンを取得してバージョン変更を確認
    _current_version = await _fetch_version()
    if _current_version:
        prev = await valkey_client.get(VERSION_KEY)
        prev_version = prev.decode() if isinstance(prev, bytes) else prev
        if prev_version and prev_version != _current_version:
            logger.info(
                "Face-detect version changed: %s -> %s, re-queuing outdated images",
                prev_version,
                _current_version,
            )
            count = await _requeue_outdated(_current_version)
            logger.info("Re-queued %d images for re-detection", count)
        await valkey_client.set(VERSION_KEY, _current_version)
        logger.info("Face-detect version: %s", _current_version)
    else:
        logger.warning("Could not fetch face-detect version, version tracking disabled")
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def _run_one(raw: str) -> None:
        async with sem:
            try:
                job = json.loads(raw)
            except json.JSONDecodeError:
                # L-5: 生データではなく長さのみログ出力
                logger.warning("Invalid face-detect job JSON (length=%d)", len(raw))
                return
            try:
                await _process_job(job)
            except Exception as e:
                await _retry_or_dead(job, str(e))

    tasks: set[asyncio.Task] = set()

    while True:
        try:
            await _update_heartbeat()

            # 準備ができた遅延ジョブを昇格
            await _promote_delayed()

            # ジョブをポップ (3秒タイムアウトのブロッキング)
            result = await valkey_client.brpop(QUEUE_KEY, timeout=3)
            if result:
                _, raw = result
                task = asyncio.create_task(_run_one(raw))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
            else:
                # ジョブなし、完了済みタスクをクリーンアップ
                pass

        except Exception:
            logger.exception("Error in face-detect worker loop")
            await asyncio.sleep(5)
