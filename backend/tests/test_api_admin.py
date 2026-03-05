from io import BytesIO
from unittest.mock import AsyncMock, patch

PNG_1x1 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01"
    b"\x00\x00\x00\x01"
    b"\x08\x02"
    b"\x00\x00\x00"
    b"\x90wS\xde"
)


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_upload_server_icon_as_admin(mock_s3, app_client, db, mock_valkey):
    from app.services.user_service import create_user
    admin = await create_user(db, "adminuser", "admin@example.com", "password1234", role="admin")

    session_id = "admin-session"
    mock_valkey.get = AsyncMock(return_value=str(admin.id))
    app_client.cookies.set("nekonoverse_session", session_id)
    mock_s3.return_value = "etag"

    resp = await app_client.post(
        "/api/v1/admin/server-icon",
        files={"file": ("icon.png", BytesIO(PNG_1x1), "image/png")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "url" in data
    mock_valkey.set.assert_called()


async def test_upload_server_icon_non_admin(authed_client, test_user):
    resp = await authed_client.post(
        "/api/v1/admin/server-icon",
        files={"file": ("icon.png", BytesIO(PNG_1x1), "image/png")},
    )
    assert resp.status_code == 403


async def test_upload_server_icon_unauthenticated(app_client, mock_valkey):
    resp = await app_client.post(
        "/api/v1/admin/server-icon",
        files={"file": ("icon.png", BytesIO(PNG_1x1), "image/png")},
    )
    assert resp.status_code == 401
