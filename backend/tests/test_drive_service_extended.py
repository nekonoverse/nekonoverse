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
    with patch("app.services.drive_service.upload_file", new_callable=AsyncMock):
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
    with patch("app.services.drive_service.delete_file", new_callable=AsyncMock):
        await delete_drive_file(db, df)
    result = await get_drive_file(db, df.id)
    assert result is None


# --- transform 再エンコード ---


async def test_upload_reencode_via_transform(db, mock_valkey, test_user):
    """transform 有効時、画像が再エンコードされ WebP で保存される。"""
    import httpx

    png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16 + b"\x00\x01" * 4
    webp_body = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 18

    fake_resp = httpx.Response(
        200,
        content=webp_body,
        headers={"content-type": "image/webp"},
        request=httpx.Request("POST", "http://localhost/transform"),
    )

    async def mock_post(*args, **kwargs):
        # no_resize=1 が送信されていることを検証
        assert kwargs.get("data", {}).get("no_resize") == "1"
        return fake_resp

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.services.drive_service.settings") as mock_settings,
        patch(
            "app.utils.http_client.make_media_transform_client",
            return_value=mock_client,
        ),
    ):
        mock_settings.media_proxy_transform_base_url = "http://localhost"

        from app.services.drive_service import _reencode_via_transform

        new_data, new_mime = await _reencode_via_transform(png_data)
        assert new_mime == "image/webp"
        assert new_data == webp_body


async def test_upload_transform_fallback_on_failure(db, mock_valkey, test_user):
    """transform 失敗時は strip_exif にフォールバックする。"""
    png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16 + b"\x00\x01" * 4

    with (
        patch("app.services.drive_service.upload_file", new_callable=AsyncMock),
        patch(
            "app.services.drive_service._reencode_via_transform",
            new_callable=AsyncMock,
            side_effect=Exception("transform down"),
        ),
        patch(
            "app.services.drive_service.strip_exif", return_value=png_data
        ) as mock_strip,
        patch(
            "app.services.drive_service.settings"
        ) as mock_settings,
    ):
        mock_settings.media_proxy_transform_enabled = True
        mock_settings.max_image_size_mb = 10
        mock_settings.max_video_size_mb = 50
        mock_settings.max_audio_size_mb = 20
        df = await upload_drive_file(db, test_user, png_data, "test.png", "image/png")
        mock_strip.assert_called_once_with(png_data, "image/png")
        assert df.mime_type == "image/png"


async def test_upload_transform_disabled(db, mock_valkey, test_user):
    """transform 無効時は従来の strip_exif が使われる。"""
    png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16 + b"\x00\x01" * 4

    with (
        patch("app.services.drive_service.upload_file", new_callable=AsyncMock),
        patch(
            "app.services.drive_service.strip_exif", return_value=png_data
        ) as mock_strip,
        patch(
            "app.services.drive_service.settings"
        ) as mock_settings,
    ):
        mock_settings.media_proxy_transform_enabled = False
        mock_settings.max_image_size_mb = 10
        mock_settings.max_video_size_mb = 50
        mock_settings.max_audio_size_mb = 20
        df = await upload_drive_file(db, test_user, png_data, "test.png", "image/png")
        mock_strip.assert_called_once_with(png_data, "image/png")
        assert df.mime_type == "image/png"
