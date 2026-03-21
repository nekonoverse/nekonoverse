from unittest.mock import AsyncMock, patch

import pytest

from app.services.drive_service import (
    _get_image_dimensions,
    _max_audio_size,
    _max_image_size,
    _max_video_size,
    delete_drive_file,
    get_drive_file,
    list_user_files,
    upload_drive_file,
)

# Minimal valid PNG: 1x1 pixel
PNG_1x1 = (
    b"\x89PNG\r\n\x1a\n"  # signature
    b"\x00\x00\x00\rIHDR"  # IHDR chunk
    b"\x00\x00\x00\x01"    # width=1
    b"\x00\x00\x00\x01"    # height=1
    b"\x08\x02"             # bit depth=8, color type=2 (RGB)
    b"\x00\x00\x00"         # compression, filter, interlace
    b"\x90wS\xde"           # CRC
)


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_upload_drive_file(mock_upload, db, test_user):
    mock_upload.return_value = "etag123"
    drive_file = await upload_drive_file(
        db=db, owner=test_user, data=PNG_1x1,
        filename="test.png", mime_type="image/png",
    )
    assert drive_file.filename == "test.png"
    assert drive_file.mime_type == "image/png"
    assert drive_file.size_bytes == len(PNG_1x1)
    assert drive_file.owner_id == test_user.id
    assert drive_file.server_file is False
    assert drive_file.width == 1
    assert drive_file.height == 1
    mock_upload.assert_called_once()


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_upload_server_file(mock_upload, db):
    mock_upload.return_value = "etag"
    drive_file = await upload_drive_file(
        db=db, owner=None, data=PNG_1x1,
        filename="icon.png", mime_type="image/png",
        server_file=True,
    )
    assert drive_file.owner_id is None
    assert drive_file.server_file is True
    assert "server/" in drive_file.s3_key


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_upload_rejects_unsupported_type(mock_upload, db, test_user):
    with pytest.raises(ValueError, match="Unsupported file type"):
        await upload_drive_file(
            db=db, owner=test_user, data=b"not an image",
            filename="test.txt", mime_type="text/plain",
        )
    mock_upload.assert_not_called()


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_upload_rejects_large_file(mock_upload, db, test_user):
    big_data = b"\x00" * (_max_image_size() + 1)
    with pytest.raises(ValueError, match="File too large"):
        await upload_drive_file(
            db=db, owner=test_user, data=big_data,
            filename="big.png", mime_type="image/png",
        )
    mock_upload.assert_not_called()


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_get_drive_file(mock_upload, db, test_user):
    mock_upload.return_value = "etag"
    created = await upload_drive_file(
        db=db, owner=test_user, data=PNG_1x1,
        filename="test.png", mime_type="image/png",
    )
    found = await get_drive_file(db, created.id)
    assert found is not None
    assert found.id == created.id


async def test_get_drive_file_not_found(db):
    import uuid
    result = await get_drive_file(db, uuid.uuid4())
    assert result is None


@patch("app.services.drive_service.delete_file", new_callable=AsyncMock)
@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_delete_drive_file(mock_upload, mock_delete, db, test_user):
    mock_upload.return_value = "etag"
    created = await upload_drive_file(
        db=db, owner=test_user, data=PNG_1x1,
        filename="test.png", mime_type="image/png",
    )
    await delete_drive_file(db, created)
    mock_delete.assert_called_once_with(created.s3_key)
    assert await get_drive_file(db, created.id) is None


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_list_user_files(mock_upload, db, test_user):
    mock_upload.return_value = "etag"
    await upload_drive_file(
        db=db, owner=test_user, data=PNG_1x1,
        filename="a.png", mime_type="image/png",
    )
    await upload_drive_file(
        db=db, owner=test_user, data=PNG_1x1,
        filename="b.png", mime_type="image/png",
    )
    files = await list_user_files(db, test_user, limit=10, offset=0)
    assert len(files) >= 2


# ── Image dimension parsing ──


def test_png_dimensions():
    w, h = _get_image_dimensions(PNG_1x1, "image/png")
    assert (w, h) == (1, 1)


def test_gif_dimensions():
    gif = b"GIF89a" + (100).to_bytes(2, "little") + (50).to_bytes(2, "little")
    w, h = _get_image_dimensions(gif, "image/gif")
    assert (w, h) == (100, 50)


def test_unknown_mime_dimensions():
    w, h = _get_image_dimensions(b"garbage", "image/avif")
    assert (w, h) == (None, None)


def test_corrupt_data_dimensions():
    w, h = _get_image_dimensions(b"", "image/png")
    assert (w, h) == (None, None)


# ── Video / Audio upload ──

# Minimal valid MP4 (ftyp box)
MP4_FTYP = (
    b"\x00\x00\x00\x14"  # box size = 20
    b"ftyp"               # box type
    b"isom"               # major brand
    b"\x00\x00\x00\x00"  # minor version
    b"isom"               # compatible brand
)

# Minimal WebM (EBML header)
WEBM_HEADER = b"\x1a\x45\xdf\xa3\x01\x00\x00\x00\x00\x00\x00\x1f"

# Minimal MP3 with ID3 tag
MP3_ID3 = b"ID3\x04\x00\x00\x00\x00\x00\x00"

# Minimal OGG
OGG_HEADER = b"OggS\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00"

# Minimal FLAC
FLAC_HEADER = b"fLaC\x00\x00\x00\x22"


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_upload_video_mp4(mock_upload, db, test_user):
    mock_upload.return_value = "etag"
    drive_file = await upload_drive_file(
        db=db, owner=test_user, data=MP4_FTYP,
        filename="test.mp4", mime_type="video/mp4",
    )
    assert drive_file.mime_type == "video/mp4"
    assert drive_file.width is None
    assert drive_file.height is None
    assert drive_file.s3_key.endswith(".mp4")


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_upload_video_webm(mock_upload, db, test_user):
    mock_upload.return_value = "etag"
    drive_file = await upload_drive_file(
        db=db, owner=test_user, data=WEBM_HEADER,
        filename="test.webm", mime_type="video/webm",
    )
    assert drive_file.mime_type == "video/webm"
    assert drive_file.s3_key.endswith(".webm")


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_upload_audio_mp3(mock_upload, db, test_user):
    mock_upload.return_value = "etag"
    drive_file = await upload_drive_file(
        db=db, owner=test_user, data=MP3_ID3,
        filename="test.mp3", mime_type="audio/mpeg",
    )
    assert drive_file.mime_type == "audio/mpeg"
    assert drive_file.s3_key.endswith(".mp3")


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_upload_audio_ogg(mock_upload, db, test_user):
    mock_upload.return_value = "etag"
    drive_file = await upload_drive_file(
        db=db, owner=test_user, data=OGG_HEADER,
        filename="test.ogg", mime_type="audio/ogg",
    )
    assert drive_file.mime_type == "audio/ogg"


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_upload_audio_flac(mock_upload, db, test_user):
    mock_upload.return_value = "etag"
    drive_file = await upload_drive_file(
        db=db, owner=test_user, data=FLAC_HEADER,
        filename="test.flac", mime_type="audio/flac",
    )
    assert drive_file.mime_type == "audio/flac"


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_video_size_limit_higher_than_image(mock_upload, db, test_user):
    """Video should allow up to 40MB (larger than image 10MB limit)."""
    big_video = MP4_FTYP + b"\x00" * (_max_image_size() + 1)
    mock_upload.return_value = "etag"
    # Should succeed (within 40MB video limit)
    drive_file = await upload_drive_file(
        db=db, owner=test_user, data=big_video,
        filename="big.mp4", mime_type="video/mp4",
    )
    assert drive_file.mime_type == "video/mp4"


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_video_rejects_over_40mb(mock_upload, db, test_user):
    big_data = b"\x00" * (_max_video_size() + 1)
    with pytest.raises(ValueError, match="File too large"):
        await upload_drive_file(
            db=db, owner=test_user, data=big_data,
            filename="huge.mp4", mime_type="video/mp4",
        )


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_audio_rejects_over_10mb(mock_upload, db, test_user):
    big_data = b"\x00" * (_max_audio_size() + 1)
    with pytest.raises(ValueError, match="File too large"):
        await upload_drive_file(
            db=db, owner=test_user, data=big_data,
            filename="huge.mp3", mime_type="audio/mpeg",
        )


# ── Configurable size limits ──


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
@patch("app.services.drive_service.settings")
async def test_custom_image_size_limit(mock_settings, mock_upload, db, test_user):
    """Image size limit should be configurable via settings."""
    mock_settings.max_image_size_mb = 5  # 5 MB
    big_data = b"\x00" * (5 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="File too large"):
        await upload_drive_file(
            db=db, owner=test_user, data=big_data,
            filename="big.png", mime_type="image/png",
        )


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
@patch("app.services.drive_service.settings")
async def test_custom_video_size_limit(mock_settings, mock_upload, db, test_user):
    """Video size limit should be configurable via settings."""
    mock_settings.max_video_size_mb = 100  # 100 MB
    mock_settings.max_image_size_mb = 10
    mock_settings.max_audio_size_mb = 10
    mock_settings.face_detect_enabled = False
    # 50MB video (over default 40MB but within custom 100MB)
    big_video = MP4_FTYP + b"\x00" * (50 * 1024 * 1024)
    mock_upload.return_value = "etag"
    drive_file = await upload_drive_file(
        db=db, owner=test_user, data=big_video,
        filename="big.mp4", mime_type="video/mp4",
    )
    assert drive_file.mime_type == "video/mp4"
