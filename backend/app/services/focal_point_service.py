"""リモート画像添付ファイルのバックグラウンドフォーカルポイント検出。"""

import asyncio
import base64
import logging
import uuid

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_IMAGE_MIMES = frozenset({
    "image/jpeg", "image/png", "image/webp", "image/gif", "image/avif", "image/apng",
})
_MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024


async def detect_remote_focal_points(
    note_id: uuid.UUID,
    attachment_ids: list[uuid.UUID],
    detect_version: str | None = None,
) -> None:
    """バックグラウンドタスク: リモート添付ファイルのフォーカルポイントを検出する。

    各リモート画像をダウンロードし、face-detectサービスを呼び出し、DBを更新し、
    ストリーミングイベントをパブリッシュする。asyncio.create_task()用に設計されており、
    例外を送出しない。
    """
    if not settings.face_detect_enabled:
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
                *(_detect_single(att, detect_version) for att in attachments),
                return_exceptions=True,
            )

            changed = False
            for att, res in zip(attachments, results):
                if isinstance(res, Exception):
                    logger.warning("Focal detection failed for %s: %s", att.id, res)
                elif res is True:
                    changed = True

            if changed:
                await db.commit()
                logger.info("Focal points updated for note %s, publishing update", note_id)
                await _publish_update(note_id)
            elif any(not isinstance(r, Exception) for r in results):
                # バージョンは記録されたがフォーカルポイントの変更なし — それでもコミット
                await db.commit()
    except Exception:
        logger.warning(
            "Background focal detection failed for note %s", note_id, exc_info=True
        )


async def _detect_single(att, detect_version: str | None = None) -> bool:
    """1つの添付ファイルのフォーカルポイントを検出する。更新された場合はTrueを返す。"""
    if att.focal_detect_version == "manual":
        return False
    if detect_version and att.focal_detect_version == detect_version:
        return False  # このバージョンで検出済み
    if not att.remote_url:
        return False
    if (att.remote_mime_type or "") not in _IMAGE_MIMES:
        return False

    image_data = await _download_image(att.remote_url)
    if not image_data:
        return False

    focal = await _call_face_detect(image_data, att.remote_width, att.remote_height)

    focal_updated = False
    if focal is not None:
        att.remote_focal_x = focal[0]
        att.remote_focal_y = focal[1]
        focal_updated = True

    # 結果に関わらずバージョンを記録
    if detect_version:
        att.focal_detect_version = detect_version

    return focal_updated


async def _download_image(url: str) -> bytes | None:
    """SSRF保護とサイズ制限付きでリモート画像をダウンロードする。

    リダイレクトを手動で追跡し、各ホップでプライベートホストかどうかを検証する。
    """
    from urllib.parse import urljoin, urlparse

    from app.utils.network import is_private_host

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    if is_private_host(parsed.hostname):
        return None

    from app.utils.http_client import make_async_client

    async with make_async_client(
        timeout=httpx.Timeout(15.0, connect=5.0),
        follow_redirects=False,
        verify=not settings.skip_ssl_verify,
    ) as client:
        current_url = url
        for _ in range(3):
            resp = await client.get(current_url)
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location")
                if not location:
                    return None
                resolved = urljoin(current_url, location)
                rp = urlparse(resolved)
                if rp.scheme not in ("http", "https") or not rp.hostname:
                    return None
                if is_private_host(rp.hostname):
                    return None
                current_url = resolved
            else:
                break
        else:
            return None

        if resp.status_code != 200:
            return None
        if len(resp.content) > _MAX_DOWNLOAD_BYTES:
            return None
        return resp.content


def _get_image_size(image_data: bytes) -> tuple[int, int] | None:
    """重い依存ライブラリなしで生バイトから画像の寸法を抽出する。"""
    import io
    import struct

    data = io.BytesIO(image_data)
    head = data.read(32)
    if len(head) < 8:
        return None

    # PNG形式
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        if len(head) >= 24:
            w, h = struct.unpack(">II", head[16:24])
            return (w, h)
        return None

    # GIF形式
    if head[:6] in (b"GIF87a", b"GIF89a"):
        w, h = struct.unpack("<HH", head[6:10])
        return (w, h)

    # JPEG形式
    if head[:2] == b"\xff\xd8":
        data.seek(2)
        while True:
            marker = data.read(2)
            if len(marker) < 2:
                return None
            if marker[0] != 0xFF:
                return None
            if marker[1] == 0xD9:
                return None
            if marker[1] in (0xC0, 0xC1, 0xC2):
                seg = data.read(7)
                if len(seg) < 7:
                    return None
                h, w = struct.unpack(">HH", seg[3:7])
                return (w, h)
            length = struct.unpack(">H", data.read(2))[0]
            data.seek(length - 2, 1)

    # WebP形式
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        # VP8
        if head[12:16] == b"VP8 ":
            if len(head) >= 30:
                w = struct.unpack("<H", head[26:28])[0] & 0x3FFF
                h = struct.unpack("<H", head[28:30])[0] & 0x3FFF
                return (w, h)
        # VP8L
        elif head[12:16] == b"VP8L":
            if len(head) >= 25:
                bits = struct.unpack("<I", head[21:25])[0]
                w = (bits & 0x3FFF) + 1
                h = ((bits >> 14) & 0x3FFF) + 1
                return (w, h)
        # VP8X (extended)
        elif head[12:16] == b"VP8X":
            data.seek(24)
            chunk = data.read(6)
            if len(chunk) >= 6:
                w = struct.unpack("<I", chunk[0:3] + b"\x00")[0] + 1
                h = struct.unpack("<I", chunk[3:6] + b"\x00")[0] + 1
                return (w, h)

    return None


async def _call_face_detect(
    image_data: bytes,
    width: int | None,
    height: int | None,
) -> tuple[float, float] | None:
    """face-detectサービスを呼び出す。(focal_x, focal_y) を返す。顔未検出時はNone。

    サーバー/ネットワークエラー時は例外を送出するため、呼び出し元で「顔未検出」と区別できる。
    """
    # メタデータがない場合は実際の画像サイズを解決
    if not width or not height:
        size = _get_image_size(image_data)
        if size:
            width, height = size
        else:
            logger.debug("Could not determine image size, skipping focal detection")
            return None

    b64 = base64.b64encode(image_data).decode("ascii")
    from app.utils.http_client import make_face_detect_client

    async with make_face_detect_client() as client:
        resp = await client.post(
            settings.face_detect_base_url,
            json={"inputs": b64, "parameters": {"threshold": 0.5}},
        )
        resp.raise_for_status()
        results = resp.json()

    from app.utils.focal import focal_from_detections

    return focal_from_detections(results, width, height)


async def _publish_update(note_id: uuid.UUID) -> None:
    """クライアントがノートを再取得するようストリーミングイベントをパブリッシュする。"""
    import json

    from app.valkey_client import valkey as valkey_client

    try:
        event = json.dumps({"event": "update", "payload": {"id": str(note_id)}})

        from sqlalchemy import select

        from app.database import async_session
        from app.models.note import Note
        from app.services.follow_service import get_follower_ids

        async with async_session() as db:
            row = (
                await db.execute(
                    select(Note.actor_id, Note.visibility).where(Note.id == note_id)
                )
            ).one_or_none()
            if row:
                actor_id, visibility = row
                if visibility == "public":
                    await valkey_client.publish("timeline:public", event)
                for fid in await get_follower_ids(db, actor_id):
                    await valkey_client.publish(f"timeline:home:{fid}", event)
    except Exception:
        logger.debug("Failed to publish focal update for %s", note_id, exc_info=True)
