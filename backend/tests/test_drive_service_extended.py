"""Extended tests for drive_service — file upload and management."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.models.drive_file import DriveFile
from app.services.drive_service import (
    delete_drive_file,
    file_to_url,
    get_drive_file,
    list_user_files,
    upload_drive_file,
)


async def _create_drive_file(db, test_user, *, filename="test.png", mime_type="image/png"):
    """Insert a DriveFile directly."""
    drive_file = DriveFile(
        owner_id=test_user.id,
        s3_key=f"uploads/{uuid.uuid4().hex}/{filename}",
        filename=filename,
        mime_type=mime_type,
        size_bytes=1024,
    )
    db.add(drive_file)
    await db.flush()
    return drive_file


async def test_get_drive_file(db, mock_valkey, test_user):
    df = await _create_drive_file(db, test_user)
    result = await get_drive_file(db, df.id)
    assert result is not None
    assert result.id == df.id


async def test_get_drive_file_not_found(db, mock_valkey):
    result = await get_drive_file(db, uuid.uuid4())
    assert result is None


async def test_list_user_files(db, mock_valkey, test_user):
    await _create_drive_file(db, test_user, filename="a.png")
    await _create_drive_file(db, test_user, filename="b.png")
    files = await list_user_files(db, test_user)
    assert len(files) >= 2


async def test_upload_drive_file_too_large(db, mock_valkey, test_user):
    large_data = b"x" * (10 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="File too large"):
        await upload_drive_file(db, test_user, large_data, "big.png", "image/png")


async def test_upload_drive_file_unsupported_type(db, mock_valkey, test_user):
    with pytest.raises(ValueError, match="Unsupported file type"):
        await upload_drive_file(db, test_user, b"data", "test.txt", "text/plain")


async def test_upload_drive_file_success(db, mock_valkey, test_user):
    # 有効なPNGヘッダ + ダミーデータ
    png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16 + b"\x00\x01" * 4
    with patch("app.storage.upload_file", new_callable=AsyncMock):
        df = await upload_drive_file(db, test_user, png_data, "test.png", "image/png")
    assert df.filename == "test.png"
    assert df.mime_type == "image/png"
    assert df.owner_id == test_user.id


async def test_file_to_url(db, mock_valkey, test_user):
    df = await _create_drive_file(db, test_user)
    url = file_to_url(df)
    assert url is not None
    assert isinstance(url, str)
    assert df.s3_key in url or "http" in url


async def test_delete_drive_file(db, mock_valkey, test_user):
    df = await _create_drive_file(db, test_user)
    with patch("app.storage.delete_file", new_callable=AsyncMock):
        await delete_drive_file(db, df)
    result = await get_drive_file(db, df.id)
    assert result is None
