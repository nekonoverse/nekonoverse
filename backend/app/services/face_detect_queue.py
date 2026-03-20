"""Valkey-based job queue for face-detect focal point detection.

Jobs are stored as JSON in a Valkey list. The worker pops jobs, processes them,
and re-enqueues on failure with exponential backoff (up to max_attempts).
Dead jobs are moved to a dead-letter list for inspection.

Job types:
  - "local":  detect focal point for a local DriveFile (by drive_file_id)
  - "remote": detect focal points for remote NoteAttachments (by note_id + attachment_ids)
"""

import asyncio
import json
import logging
import time
import uuid

from app.config import settings
from app.valkey_client import valkey as valkey_client

logger = logging.getLogger(__name__)

QUEUE_KEY = "face_detect:queue"
DELAYED_KEY = "face_detect:delayed"  # sorted set: score=run_at_timestamp
DEAD_KEY = "face_detect:dead"
HEARTBEAT_KEY = "worker:face_detect:heartbeat"

MAX_ATTEMPTS = 5
MAX_CONCURRENT = 4


async def enqueue_local(drive_file_id: uuid.UUID) -> None:
    """Enqueue face detection for a local DriveFile."""
    if not settings.face_detect_enabled:
        return
    job = {
        "type": "local",
        "drive_file_id": str(drive_file_id),
        "attempts": 0,
        "created_at": time.time(),
    }
    await valkey_client.lpush(QUEUE_KEY, json.dumps(job))
    logger.debug("Enqueued local face-detect job for %s", drive_file_id)


async def enqueue_remote(note_id: uuid.UUID, attachment_ids: list[uuid.UUID]) -> None:
    """Enqueue face detection for remote NoteAttachments."""
    if not settings.face_detect_enabled:
        return
    job = {
        "type": "remote",
        "note_id": str(note_id),
        "attachment_ids": [str(a) for a in attachment_ids],
        "attempts": 0,
        "created_at": time.time(),
    }
    await valkey_client.lpush(QUEUE_KEY, json.dumps(job))
    logger.debug("Enqueued remote face-detect job for note %s (%d attachments)",
                 note_id, len(attachment_ids))


async def _process_local(job: dict) -> None:
    """Process a local DriveFile face detection job."""
    from sqlalchemy import select

    from app.database import async_session
    from app.models.drive_file import DriveFile
    from app.services.drive_service import auto_detect_focal_point

    drive_file_id = uuid.UUID(job["drive_file_id"])

    async with async_session() as db:
        result = await db.execute(
            select(DriveFile).where(DriveFile.id == drive_file_id)
        )
        drive_file = result.scalar_one_or_none()
        if not drive_file:
            logger.warning("DriveFile %s not found, skipping", drive_file_id)
            return
        if drive_file.focal_x is not None:
            return  # Already set

        await auto_detect_focal_point(db, drive_file)


async def _process_remote(job: dict) -> None:
    """Process remote NoteAttachment face detection job."""
    from app.services.focal_point_service import detect_remote_focal_points

    note_id = uuid.UUID(job["note_id"])
    attachment_ids = [uuid.UUID(a) for a in job["attachment_ids"]]
    await detect_remote_focal_points(note_id, attachment_ids)


async def _process_job(job: dict) -> None:
    """Route and process a single job."""
    job_type = job.get("type")
    if job_type == "local":
        await _process_local(job)
    elif job_type == "remote":
        await _process_remote(job)
    else:
        logger.warning("Unknown face-detect job type: %s", job_type)


async def _retry_or_dead(job: dict, error: str) -> None:
    """Re-enqueue with backoff or move to dead-letter."""
    job["attempts"] = job.get("attempts", 0) + 1
    job["last_error"] = error

    if job["attempts"] >= MAX_ATTEMPTS:
        await valkey_client.lpush(DEAD_KEY, json.dumps(job))
        logger.warning("Face-detect job dead-lettered after %d attempts: %s",
                       job["attempts"], error)
    else:
        delay = min(30 * (2 ** job["attempts"]), 3600)  # Max 1 hour
        run_at = time.time() + delay
        await valkey_client.zadd(DELAYED_KEY, {json.dumps(job): run_at})
        logger.info("Face-detect job retry #%d in %ds: %s",
                    job["attempts"], delay, error)


async def _promote_delayed() -> int:
    """Move delayed jobs whose run_at has passed back to the main queue."""
    now = time.time()
    # Get jobs ready to run
    ready = await valkey_client.zrangebyscore(DELAYED_KEY, "-inf", str(now), start=0, num=50)
    if not ready:
        return 0
    for raw in ready:
        await valkey_client.lpush(QUEUE_KEY, raw)
    await valkey_client.zremrangebyscore(DELAYED_KEY, "-inf", str(now))
    return len(ready)


async def _update_heartbeat() -> None:
    """Update face-detect worker heartbeat."""
    try:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        await valkey_client.set(HEARTBEAT_KEY, now, ex=30)
    except Exception:
        pass


async def run_face_detect_loop() -> None:
    """Main face-detect worker loop.

    Pops jobs from the Valkey queue, processes them with a concurrency semaphore,
    and handles retries with exponential backoff.
    """
    if not settings.face_detect_enabled:
        logger.info("FACE_DETECT_URL/UDS not set, face-detect worker idle")
        # Still run the loop so we can start processing if config changes
        while True:
            await asyncio.sleep(30)

    logger.info("Face-detect worker started (max_concurrent=%d)", MAX_CONCURRENT)
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def _run_one(raw: str) -> None:
        async with sem:
            try:
                job = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Invalid face-detect job JSON: %s", raw[:200])
                return
            try:
                await _process_job(job)
            except Exception as e:
                await _retry_or_dead(job, str(e))

    tasks: set[asyncio.Task] = set()

    while True:
        try:
            await _update_heartbeat()

            # Promote any delayed jobs that are ready
            await _promote_delayed()

            # Try to pop a job (blocking with 3s timeout)
            result = await valkey_client.brpop(QUEUE_KEY, timeout=3)
            if result:
                _, raw = result
                task = asyncio.create_task(_run_one(raw))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
            else:
                # No job available, clean up completed tasks
                pass

        except Exception:
            logger.exception("Error in face-detect worker loop")
            await asyncio.sleep(5)
