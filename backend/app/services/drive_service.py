"""ドライブファイル管理サービス。"""

import base64
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
    "image/apng",
}

ALLOWED_VIDEO_TYPES = {
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "video/x-matroska",
}

ALLOWED_AUDIO_TYPES = {
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/flac",
    "audio/aac",
    "audio/webm",
    "audio/mp4",
}

ALLOWED_MEDIA_TYPES = ALLOWED_IMAGE_TYPES | ALLOWED_VIDEO_TYPES | ALLOWED_AUDIO_TYPES

def _max_image_size() -> int:
    return settings.max_image_size_mb * 1024 * 1024


def _max_video_size() -> int:
    return settings.max_video_size_mb * 1024 * 1024


def _max_audio_size() -> int:
    return settings.max_audio_size_mb * 1024 * 1024

# マジックバイト: MIMEタイプと実際のファイルヘッダーの対応
_MAGIC_BYTES: dict[str, list[bytes]] = {
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/apng": [b"\x89PNG\r\n\x1a\n"],
    "image/gif": [b"GIF87a", b"GIF89a"],
    "image/webp": [b"RIFF"],  # RIFF????WEBP
    # L-12: AVIFのftypボックスチェック追加
    "image/avif": [b"\x00\x00\x00"],  # ftypボックス (先頭4バイトはサイズ、8-11バイトが"ftyp")
    # 動画
    "video/webm": [b"\x1a\x45\xdf\xa3"],  # EBML header (Matroska/WebM)
    "video/x-matroska": [b"\x1a\x45\xdf\xa3"],
    # 音声
    "audio/mpeg": [b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"],  # ID3 tag or MPEG sync
    "audio/ogg": [b"OggS"],
    "audio/wav": [b"RIFF"],  # RIFF????WAVE
    "audio/flac": [b"fLaC"],
    "audio/webm": [b"\x1a\x45\xdf\xa3"],
}


def _validate_magic_bytes(data: bytes, mime_type: str) -> None:
    """ファイル内容が申告されたMIMEタイプと一致するか検証する。"""
    # ftyp ボックスベースのフォーマット (AVIF, MP4, QuickTime, AAC/M4A)
    _FTYP_BRANDS: dict[str, set[bytes]] = {
        "image/avif": {b"avif", b"avis", b"mif1"},
        "video/mp4": {b"isom", b"iso2", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1", b"dash"},
        "video/quicktime": {b"qt  "},
        "audio/aac": {b"isom", b"iso2", b"M4A ", b"mp42"},
        "audio/mp4": {b"isom", b"iso2", b"M4A ", b"mp42"},
    }
    brands = _FTYP_BRANDS.get(mime_type)
    if brands is not None:
        if len(data) >= 12 and data[4:8] == b"ftyp":
            if data[8:12] in brands:
                return
        raise ValueError(f"File content does not match declared type {mime_type}")

    signatures = _MAGIC_BYTES.get(mime_type)
    if not signatures:
        return  # 検証定義がないMIMEタイプはスキップ
    for sig in signatures:
        if data[:len(sig)] == sig:
            return
    raise ValueError(f"File content does not match declared type {mime_type}")

# PNGシグネチャ
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _remove_jpeg_app1(data: bytes) -> bytes:
    """JPEGからAPP1 (EXIF) セグメントをバイトレベルで除去する (画像デコード不要)。"""
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
        # スタンドアロンマーカー (長さフィールドなし)
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
    """JPEGからEXIFをバイトレベルで除去する。画像デコード不要。"""
    try:
        return _remove_jpeg_app1(data)
    except Exception:
        return data


def _strip_exif_png(data: bytes) -> bytes:
    """PNGからeXIfチャンクをバイトレベルで除去する (画像デコード不要)。"""
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
    """画像データからEXIFメタデータをバイトレベルで除去する (画像デコード不要)。

    JPEG: APP1セグメントを除去。PNG: eXIfチャンクを除去。
    その他のフォーマット: そのまま返す。
    向き補正はクライアント側の責任。
    """
    if mime_type == "image/jpeg":
        return _strip_exif_jpeg(data)
    if mime_type == "image/png":
        return _strip_exif_png(data)
    return data


async def _reencode_via_transform(data: bytes) -> tuple[bytes, str]:
    """media-proxy-rs の /transform にPOSTしてデコード→再エンコードする。

    元の解像度を維持するため no_resize=1 を指定する。
    再エンコードによりEXIF等メタデータ・LSBステガノグラフィが除去される。
    """
    from app.utils.http_client import make_media_transform_client

    async with make_media_transform_client() as client:
        base = settings.media_proxy_transform_base_url
        url = f"{base}/transform" if not base.endswith("/transform") else base
        resp = await client.post(
            url,
            files={"file": ("image", data)},
            data={"no_resize": "1"},
        )
        resp.raise_for_status()
        new_mime = resp.headers.get("content-type", "image/webp")
        return resp.content, new_mime


async def upload_drive_file(
    db: AsyncSession,
    owner: User | None,
    data: bytes,
    filename: str,
    mime_type: str,
    description: str | None = None,
    server_file: bool = False,
) -> DriveFile:
    # ファイルサイズ上限をMIMEタイプに応じて分岐
    if mime_type.startswith("video/"):
        max_size = _max_video_size()
    elif mime_type.startswith("audio/"):
        max_size = _max_audio_size()
    else:
        max_size = _max_image_size()
    if len(data) > max_size:
        raise ValueError(f"File too large (max {max_size // 1024 // 1024} MB)")

    if mime_type not in ALLOWED_MEDIA_TYPES:
        raise ValueError(f"Unsupported file type: {mime_type}")

    # 容量制限チェック (サーバーファイルはスキップ)
    if owner and not server_file:
        from app.services.quota_service import check_quota

        ok, usage, limit = await check_quota(db, owner, len(data))
        if not ok:
            raise ValueError("Storage quota exceeded")

    # マジックバイト検証: 申告されたMIMEタイプと実際のファイル内容が一致するか確認
    _validate_magic_bytes(data, mime_type)

    # 保存前にメタデータを除去 (プライバシー保護の多層防御、画像のみ)
    # media-proxy-rs が有効な場合はデコード→再エンコードで全フォーマットのメタデータ + LSBステガノを除去
    # 無効 or 失敗時は従来の strip_exif にフォールバック (JPEG/PNGのみ)
    if mime_type.startswith("image/"):
        transformed = False
        if settings.media_proxy_transform_enabled:
            try:
                new_data, new_mime = await _reencode_via_transform(data)
                # レスポンス検証: MIMEタイプが許可リストに含まれるか
                if new_mime not in ALLOWED_IMAGE_TYPES:
                    raise ValueError(
                        f"Transform returned unexpected MIME type: {new_mime}"
                    )
                # レスポンス検証: サイズ上限を超えていないか
                if len(new_data) > max_size:
                    raise ValueError(
                        f"Transform result too large: {len(new_data)} bytes"
                    )
                data = new_data
                mime_type = new_mime
                transformed = True
            except Exception:
                logger.warning("Transform re-encode failed, falling back to strip_exif")
        if not transformed:
            data = strip_exif(data, mime_type)

    file_id = uuid.uuid4()
    ext = _extension_for_mime(mime_type)
    prefix = "server" if server_file else f"u/{owner.id}" if owner else "server"
    s3_key = f"{prefix}/{file_id}{ext}"

    # 画像のみ寸法を抽出（動画・音声はNone）— 再エンコード後のバイトで計測
    width, height = (
        _get_image_dimensions(data, mime_type) if mime_type.startswith("image/") else (None, None)
    )

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
    """ドライブファイルの説明文やフォーカルポイントを更新する。"""
    if description is not None:
        drive_file.description = description
    if focal_x is not None and math.isfinite(focal_x):
        drive_file.focal_x = max(-1.0, min(1.0, focal_x))
    if focal_y is not None and math.isfinite(focal_y):
        drive_file.focal_y = max(-1.0, min(1.0, focal_y))
    if focal_x is not None or focal_y is not None:
        drive_file.focal_detect_version = "manual"
    await db.commit()
    await db.refresh(drive_file)
    return drive_file


async def auto_detect_focal_point(
    db: AsyncSession,
    drive_file: DriveFile,
    image_data: bytes | None = None,
    detect_version: str | None = None,
) -> None:
    """顔検出サービスを呼び出してフォーカルポイントを自動設定する。失敗時は無視する。

    Args:
        db: データベースセッション。
        drive_file: フォーカルポイントを検出するドライブファイル。
        image_data: 生の画像バイト。未指定の場合はS3からダウンロードする。
        detect_version: 現在のface-detectサービスバージョン。再検出のスキップと
            使用バージョンの記録に使用される。
    """
    if not settings.face_detect_enabled:
        return
    base_url = settings.face_detect_base_url
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        logger.warning("Invalid face_detect_url scheme: %s", parsed.scheme)
        return
    if drive_file.focal_detect_version == "manual":
        return  # ユーザー手動設定のフォーカルポイント — 上書きしない
    if detect_version and drive_file.focal_detect_version == detect_version:
        return  # このバージョンで検出済み (顔の有無を問わず)
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
        if focal:
            drive_file.focal_x, drive_file.focal_y = focal
            logger.info(
                "Focal point set for %s: (%.2f, %.2f)", drive_file.id, focal[0], focal[1]
            )
        else:
            logger.info("No face detected for %s", drive_file.id)

        # 結果に関わらずバージョンを記録 (顔が検出されたかどうかを問わず)
        if detect_version:
            drive_file.focal_detect_version = detect_version
        await db.commit()
    except Exception:
        logger.warning(
            "Face detection failed for %s", drive_file.id, exc_info=True
        )


async def _read_file_data(drive_file: DriveFile) -> bytes | None:
    """顔検出用にS3からファイルデータを読み取る。"""
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
        "image/apng": ".apng",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
        "video/x-matroska": ".mkv",
        "audio/mpeg": ".mp3",
        "audio/ogg": ".ogg",
        "audio/wav": ".wav",
        "audio/flac": ".flac",
        "audio/aac": ".aac",
        "audio/webm": ".weba",
        "audio/mp4": ".m4a",
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
