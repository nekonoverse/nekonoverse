"""Drive file management service."""

import base64
import io
import logging
import math
import uuid
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.drive_file import DriveFile
from app.models.user import User
from app.storage import delete_file, get_public_url, upload_file

logger = logging.getLogger(__name__)

ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/avif",
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

# マジックバイト: MIMEタイプと実際のファイルヘッダーの対応
_MAGIC_BYTES: dict[str, list[bytes]] = {
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/gif": [b"GIF87a", b"GIF89a"],
    "image/webp": [b"RIFF"],  # RIFF????WEBP
    # L-12: AVIFのftypボックスチェック追加
    "image/avif": [b"\x00\x00\x00"],  # ftypボックス (先頭4バイトはサイズ、8-11バイトが"ftyp")
}


def _validate_magic_bytes(data: bytes, mime_type: str) -> None:
    """Validate that file content matches the declared MIME type."""
    # L-12: AVIFのftypボックス検証
    if mime_type == "image/avif":
        if len(data) >= 12 and data[4:8] == b"ftyp":
            ftyp_brand = data[8:12]
            if ftyp_brand in (b"avif", b"avis", b"mif1"):
                return
        raise ValueError(f"File content does not match declared type {mime_type}")

    signatures = _MAGIC_BYTES.get(mime_type)
    if not signatures:
        return  # 検証定義がないMIMEタイプはスキップ
    for sig in signatures:
        if data[:len(sig)] == sig:
            return
    raise ValueError(f"File content does not match declared type {mime_type}")

# PNG signature
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _remove_jpeg_app1(data: bytes) -> bytes:
    """Remove APP1 (EXIF) segments from JPEG at byte level (no image decoding)."""
    import struct

    if len(data) < 2 or data[:2] != b"\xff\xd8":
        return data
    result = bytearray(b"\xff\xd8")
    pos = 2
    while pos < len(data):
        if data[pos] != 0xFF:
            result.extend(data[pos:])
            break
        marker = data[pos : pos + 2]
        if marker == b"\xff\xda":  # SOS — rest is image data
            result.extend(data[pos:])
            break
        # Standalone markers (no length field)
        if marker[1] in range(0xD0, 0xDA) or marker == b"\xff\x01":
            result.extend(marker)
            pos += 2
            continue
        if pos + 4 > len(data):
            result.extend(data[pos:])
            break
        length = struct.unpack(">H", data[pos + 2 : pos + 4])[0]
        segment_end = pos + 2 + length
        if marker == b"\xff\xe1":  # APP1 = EXIF
            pos = segment_end
            continue
        result.extend(data[pos:segment_end])
        pos = segment_end
    return bytes(result)


def _strip_exif_jpeg(data: bytes) -> bytes:
    """Remove EXIF from JPEG at byte level. No image decoding."""
    try:
        return _remove_jpeg_app1(data)
    except Exception:
        return data


def _strip_exif_png(data: bytes) -> bytes:
    """Remove eXIf chunk from PNG at byte level (no image decoding)."""
    if len(data) < 8 or data[:8] != _PNG_SIGNATURE:
        return data
    result = bytearray(data[:8])
    pos = 8
    while pos + 8 <= len(data):
        length = int.from_bytes(data[pos : pos + 4], "big")
        chunk_type = data[pos + 4 : pos + 8]
        chunk_end = pos + 12 + length  # 4(len) + 4(type) + data + 4(crc)
        if chunk_end > len(data):
            result.extend(data[pos:])
            break
        if chunk_type == b"eXIf":
            pos = chunk_end
            continue
        result.extend(data[pos:chunk_end])
        pos = chunk_end
    return bytes(result)


def strip_exif(data: bytes, mime_type: str) -> bytes:
    """Remove EXIF metadata from image data at byte level (no image decoding).

    JPEG: Removes APP1 segments. PNG: Removes eXIf chunks.
    Other formats: Returned unchanged.
    Orientation correction is the client's responsibility.
    """
    if mime_type == "image/jpeg":
        return _strip_exif_jpeg(data)
    if mime_type == "image/png":
        return _strip_exif_png(data)
    return data


async def upload_drive_file(
    db: AsyncSession,
    owner: User | None,
    data: bytes,
    filename: str,
    mime_type: str,
    description: str | None = None,
    server_file: bool = False,
) -> DriveFile:
    if len(data) > MAX_FILE_SIZE:
        raise ValueError(f"File too large (max {MAX_FILE_SIZE // 1024 // 1024} MB)")

    if mime_type not in ALLOWED_IMAGE_TYPES:
        raise ValueError(f"Unsupported file type: {mime_type}")

    # Quota check (skip for server files)
    if owner and not server_file:
        from app.services.quota_service import check_quota

        ok, usage, limit = await check_quota(db, owner, len(data))
        if not ok:
            raise ValueError("Storage quota exceeded")

    # マジックバイト検証: 申告されたMIMEタイプと実際のファイル内容が一致するか確認
    _validate_magic_bytes(data, mime_type)

    # Strip EXIF metadata before storing (defense-in-depth for privacy)
    data = strip_exif(data, mime_type)

    file_id = uuid.uuid4()
    ext = _extension_for_mime(mime_type)
    prefix = "server" if server_file else f"u/{owner.id}" if owner else "server"
    s3_key = f"{prefix}/{file_id}{ext}"

    width, height = _get_image_dimensions(data, mime_type)

    await upload_file(s3_key, data, mime_type)

    drive_file = DriveFile(
        id=file_id,
        owner_id=owner.id if owner else None,
        s3_key=s3_key,
        filename=filename,
        mime_type=mime_type,
        size_bytes=len(data),
        width=width,
        height=height,
        description=description,
        server_file=server_file,
    )
    db.add(drive_file)
    await db.commit()
    await db.refresh(drive_file)
    return drive_file


async def get_drive_file(db: AsyncSession, file_id: uuid.UUID) -> DriveFile | None:
    result = await db.execute(select(DriveFile).where(DriveFile.id == file_id))
    return result.scalar_one_or_none()


async def delete_drive_file(db: AsyncSession, drive_file: DriveFile) -> None:
    await delete_file(drive_file.s3_key)
    await db.delete(drive_file)
    await db.commit()


async def list_user_files(
    db: AsyncSession,
    user: User,
    limit: int = 50,
    offset: int = 0,
) -> list[DriveFile]:
    result = await db.execute(
        select(DriveFile)
        .where(DriveFile.owner_id == user.id, DriveFile.server_file.is_(False))
        .order_by(DriveFile.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def update_drive_file_meta(
    db: AsyncSession,
    drive_file: DriveFile,
    description: str | None = None,
    focal_x: float | None = None,
    focal_y: float | None = None,
) -> DriveFile:
    """Update description and/or focal point of a drive file."""
    if description is not None:
        drive_file.description = description
    if focal_x is not None and math.isfinite(focal_x):
        drive_file.focal_x = max(-1.0, min(1.0, focal_x))
    if focal_y is not None and math.isfinite(focal_y):
        drive_file.focal_y = max(-1.0, min(1.0, focal_y))
    await db.commit()
    await db.refresh(drive_file)
    return drive_file


async def auto_detect_focal_point(
    db: AsyncSession,
    drive_file: DriveFile,
    image_data: bytes | None = None,
) -> None:
    """Call face detection service to auto-set focal point. Fails silently.

    Args:
        db: Database session.
        drive_file: The drive file to detect focal point for.
        image_data: Raw image bytes. If not provided, downloads from S3.
    """
    if not settings.face_detect_enabled:
        return
    base_url = settings.face_detect_base_url
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        logger.warning("Invalid face_detect_url scheme: %s", parsed.scheme)
        return
    if drive_file.focal_x is not None:
        return  # Already set manually
    if not drive_file.mime_type.startswith("image/"):
        return

    try:
        if not image_data:
            image_data = await _read_file_data(drive_file)
            if not image_data:
                logger.warning(
                    "Could not read file %s from S3 for face detection",
                    drive_file.s3_key,
                )
                return

        logger.info("Running face detection for %s", drive_file.id)

        b64 = base64.b64encode(image_data).decode("ascii")
        from app.utils.http_client import make_face_detect_client

        async with make_face_detect_client() as client:
            resp = await client.post(
                base_url,
                json={"inputs": b64, "parameters": {"threshold": 0.5}},
            )
            resp.raise_for_status()
            results = resp.json()

        from app.utils.focal import focal_from_detections

        focal = focal_from_detections(
            results, drive_file.width or 1, drive_file.height or 1
        )
        if not focal:
            logger.info("No face detected for %s", drive_file.id)
            return

        drive_file.focal_x, drive_file.focal_y = focal
        await db.commit()
        logger.info(
            "Focal point set for %s: (%.2f, %.2f)", drive_file.id, focal[0], focal[1]
        )
    except Exception:
        logger.warning(
            "Face detection failed for %s", drive_file.id, exc_info=True
        )


async def _read_file_data(drive_file: DriveFile) -> bytes | None:
    """Read file data from S3 for face detection."""
    try:
        from app.storage import download_file

        return await download_file(drive_file.s3_key)
    except Exception:
        logger.debug("Could not read file %s for face detection", drive_file.s3_key)
        return None


def file_to_url(drive_file: DriveFile) -> str:
    return get_public_url(drive_file.s3_key)


def _extension_for_mime(mime_type: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/avif": ".avif",
    }.get(mime_type, "")


def _get_image_dimensions(data: bytes, mime_type: str) -> tuple[int | None, int | None]:
    try:
        if mime_type == "image/png" and len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
            return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        elif mime_type == "image/jpeg":
            i = 2
            while i < len(data) - 9:
                if data[i] != 0xFF:
                    break
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2):
                    w = int.from_bytes(data[i + 7 : i + 9], "big")
                    h = int.from_bytes(data[i + 5 : i + 7], "big")
                    return w, h
                length = int.from_bytes(data[i + 2 : i + 4], "big")
                i += 2 + length
        elif mime_type == "image/gif" and len(data) >= 10 and data[:3] == b"GIF":
            return int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
        elif (
            mime_type == "image/webp"
            and len(data) >= 30
            and data[:4] == b"RIFF"
            and data[8:12] == b"WEBP"
        ):
            if data[12:16] == b"VP8 ":
                w = int.from_bytes(data[26:28], "little") & 0x3FFF
                h = int.from_bytes(data[28:30], "little") & 0x3FFF
                return w, h
    except Exception:
        pass
    return None, None
