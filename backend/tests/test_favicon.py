"""Tests for favicon.ico generation and endpoint."""

import io
from unittest.mock import AsyncMock, patch

import pytest

PNG_1x1 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01"
    b"\x00\x00\x00\x01"
    b"\x08\x02"
    b"\x00\x00\x00"
    b"\x90wS\xde"
)


# ── Unit tests for generate_ico_bytes ────────────────────────────────


def test_generate_ico_bytes_from_png():
    """Generate ICO bytes from a valid PNG image."""
    from PIL import Image

    # Create a proper 64x64 PNG for ICO generation
    img = Image.new("RGBA", (64, 64), (255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_data = buf.getvalue()

    from app.services.icon_service import generate_ico_bytes

    ico_data = generate_ico_bytes(png_data)
    assert ico_data is not None
    # ICO files start with \x00\x00\x01\x00
    assert ico_data[:4] == b"\x00\x00\x01\x00"


def test_generate_ico_bytes_invalid_data():
    """Return None for invalid image data."""
    from app.services.icon_service import generate_ico_bytes

    result = generate_ico_bytes(b"not an image")
    assert result is None


# ── Integration: upload_server_icon generates favicon ────────────────


async def make_admin(db, mock_valkey, app_client, *, username="adminuser"):
    from app.services.user_service import create_user

    user = await create_user(
        db, username, f"{username}@example.com", "password1234", role="admin"
    )
    mock_valkey.get = AsyncMock(return_value=str(user.id))
    app_client.cookies.set("nekonoverse_session", "admin-session")
    return user


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
@patch("app.services.icon_service.upload_file", new_callable=AsyncMock)
async def test_server_icon_upload_generates_favicon(
    mock_icon_s3, mock_drive_s3, app_client, db, mock_valkey
):
    """Uploading a server icon should also generate and store a favicon.ico."""
    await make_admin(db, mock_valkey, app_client)
    mock_drive_s3.return_value = "etag"
    mock_icon_s3.return_value = "etag"

    from PIL import Image

    img = Image.new("RGBA", (64, 64), (0, 128, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_data = buf.getvalue()

    resp = await app_client.post(
        "/api/v1/admin/server-icon",
        files={"file": ("icon.png", io.BytesIO(png_data), "image/png")},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # icon_service uploads 3 files: 512 PNG, 192 PNG, ICO
    assert mock_icon_s3.call_count >= 3

    # Check that favicon_ico_url was saved in server_settings
    from sqlalchemy import select

    from app.models.server_setting import ServerSetting

    result = await db.execute(
        select(ServerSetting).where(ServerSetting.key == "favicon_ico_url")
    )
    setting = result.scalar_one_or_none()
    assert setting is not None
    assert "favicon-" in setting.value

    # Check PWA icon URLs were saved
    result = await db.execute(
        select(ServerSetting).where(ServerSetting.key == "pwa_icon_192_url")
    )
    assert result.scalar_one_or_none() is not None

    result = await db.execute(
        select(ServerSetting).where(ServerSetting.key == "pwa_icon_512_url")
    )
    assert result.scalar_one_or_none() is not None


# ── GET /favicon.ico endpoint ────────────────────────────────────────


async def test_favicon_ico_endpoint_not_configured(app_client, db, mock_valkey):
    """Return default SVG when no favicon is configured."""
    resp = await app_client.get("/favicon.ico")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")


async def test_favicon_ico_endpoint_redirect(app_client, db, mock_valkey):
    """Redirect to the configured favicon URL."""
    from app.services.server_settings_service import set_setting

    favicon_url = "https://media.example.com/server/favicon-abc123.ico"
    await set_setting(db, "favicon_ico_url", favicon_url)
    await db.flush()

    resp = await app_client.get("/favicon.ico", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == favicon_url
