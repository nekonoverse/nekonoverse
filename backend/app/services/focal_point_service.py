"""Background focal point detection for remote image attachments."""

import asyncio
import base64
import logging
import uuid

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_IMAGE_MIMES = frozenset({
    "image/jpeg", "image/png", "image/webp", "image/gif", "image/avif",
})
_MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024


async def detect_remote_focal_points(
    note_id: uuid.UUID,
    attachment_ids: list[uuid.UUID],
) -> None:
    """Background task: detect focal points for remote attachments.

    Downloads each remote image, calls face-detect service, updates DB,
    and publishes a streaming event.  Designed for asyncio.create_task();
    never raises.
    """
    if not settings.face_detect_url:
        return

    from app.database import async_session

    try:
        async with async_session() as db:
            from sqlalchemy import select

            from app.models.note_attachment import NoteAttachment

            rows = await db.execute(
                select(NoteAttachment).where(
                    NoteAttachment.id.in_(attachment_ids),
                )
            )
            attachments = list(rows.scalars().all())

            results = await asyncio.gather(
                *(_detect_single(att) for att in attachments),
                return_exceptions=True,
            )

            updated = False
            for att, res in zip(attachments, results):
                if isinstance(res, Exception):
                    logger.debug("Focal detection failed for %s: %s", att.id, res)
                elif res is True:
                    updated = True

            if updated:
                await db.commit()
                await _publish_update(note_id)
    except Exception:
        logger.debug("Background focal detection failed for note %s", note_id, exc_info=True)


async def _detect_single(att) -> bool:
    """Detect focal point for one attachment. Returns True if updated."""
    if att.remote_focal_x is not None:
        return False
    if not att.remote_url:
        return False
    if (att.remote_mime_type or "") not in _IMAGE_MIMES:
        return False

    image_data = await _download_image(att.remote_url)
    if not image_data:
        return False

    focal = await _call_face_detect(image_data, att.remote_width, att.remote_height)
    if focal is None:
        return False

    att.remote_focal_x = focal[0]
    att.remote_focal_y = focal[1]
    return True


async def _download_image(url: str) -> bytes | None:
    """Download remote image with SSRF protection and size limit."""
    from urllib.parse import urlparse

    from app.api.mastodon.media_proxy import _is_private_host

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    if _is_private_host(parsed.hostname):
        return None

    try:
        from app.utils.http_client import make_async_client

        async with make_async_client(
            timeout=httpx.Timeout(15.0, connect=5.0),
            follow_redirects=True,
            max_redirects=3,
            verify=not settings.skip_ssl_verify,
        ) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None
            if len(resp.content) > _MAX_DOWNLOAD_BYTES:
                return None
            return resp.content
    except Exception:
        return None


async def _call_face_detect(
    image_data: bytes,
    width: int | None,
    height: int | None,
) -> tuple[float, float] | None:
    """Call face-detect service. Returns (focal_x, focal_y) or None."""
    b64 = base64.b64encode(image_data).decode("ascii")
    try:
        from app.utils.http_client import make_face_detect_client

        async with make_face_detect_client() as client:
            resp = await client.post(
                settings.face_detect_url,
                json={"inputs": b64, "parameters": {"threshold": 0.5}},
            )
            resp.raise_for_status()
            results = resp.json()

        if not results:
            return None

        box = results[0]["box"]
        cx = (box["xmin"] + box["xmax"]) / 2
        cy = (box["ymin"] + box["ymax"]) / 2

        w = width or 1
        h = height or 1
        focal_x = max(-1.0, min(1.0, (cx / w) * 2 - 1))
        focal_y = max(-1.0, min(1.0, 1 - (cy / h) * 2))
        return (focal_x, focal_y)
    except Exception:
        return None


async def _publish_update(note_id: uuid.UUID) -> None:
    """Publish streaming event so clients re-fetch the note."""
    import json

    from app.valkey_client import valkey as valkey_client

    try:
        event = json.dumps({"event": "update", "payload": {"id": str(note_id)}})
        await valkey_client.publish("timeline:public", event)

        from sqlalchemy import select

        from app.database import async_session
        from app.models.note import Note
        from app.services.follow_service import get_follower_ids

        async with async_session() as db:
            actor_id = (
                await db.execute(select(Note.actor_id).where(Note.id == note_id))
            ).scalar_one_or_none()
            if actor_id:
                for fid in await get_follower_ids(db, actor_id):
                    await valkey_client.publish(f"timeline:home:{fid}", event)
    except Exception:
        logger.debug("Failed to publish focal update for %s", note_id, exc_info=True)
