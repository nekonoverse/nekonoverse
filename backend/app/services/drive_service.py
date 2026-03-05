"""Drive file management service."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_file import DriveFile
from app.models.user import User
from app.storage import delete_file, get_public_url, upload_file

ALLOWED_IMAGE_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/avif",
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


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
    db: AsyncSession, user: User, limit: int = 50, offset: int = 0,
) -> list[DriveFile]:
    result = await db.execute(
        select(DriveFile)
        .where(DriveFile.owner_id == user.id, DriveFile.server_file.is_(False))
        .order_by(DriveFile.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


def file_to_url(drive_file: DriveFile) -> str:
    return get_public_url(drive_file.s3_key)


def _extension_for_mime(mime_type: str) -> str:
    return {
        "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
        "image/webp": ".webp", "image/avif": ".avif",
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
                    return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
                length = int.from_bytes(data[i + 2:i + 4], "big")
                i += 2 + length
        elif mime_type == "image/gif" and len(data) >= 10 and data[:3] == b"GIF":
            return int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
        elif mime_type == "image/webp" and len(data) >= 30 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            if data[12:16] == b"VP8 ":
                return int.from_bytes(data[26:28], "little") & 0x3FFF, int.from_bytes(data[28:30], "little") & 0x3FFF
    except Exception:
        pass
    return None, None
