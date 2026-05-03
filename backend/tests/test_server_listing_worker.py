"""サーバーリスト通知ワーカーのテスト。"""

from unittest.mock import AsyncMock, patch

import pytest


async def _setup_admin(db):
    """テスト用の管理者ユーザーを作成する。"""
    from app.services.user_service import create_user

    return await create_user(
        db,
        "listing_admin",
        "ladmin@example.com",
        "password1234",
        role="admin",
        display_name="Admin User",
    )


async def _set_listing_settings(
    db, *, enabled=True, url="https://directory.example.com/api/v1/servers"
):
    """サーバーリスト設定をDBに書き込む。"""
    from app.services.server_settings_service import set_setting

    await set_setting(db, "server_listing_enabled", "true" if enabled else "false")
    await set_setting(db, "server_listing_url", url)
    await set_setting(db, "server_name", "Test Server")
    await set_setting(db, "server_description", "A test server")
    await set_setting(db, "registration_mode", "open")
    await db.commit()


async def test_collect_server_info(db, mock_valkey):
    """_collect_server_info がサーバー情報を正しく収集する。"""
    from app.services.server_listing_worker import _collect_server_info

    await _setup_admin(db)
    await _set_listing_settings(db)

    info = await _collect_server_info(db)
    assert info["name"] == "Test Server"
    assert info["admin_name"] == "Admin User"
    assert info["description"] == "A test server"
    assert info["registration_mode"] == "open"
    assert info["listing_enabled"] is True
    assert info["version"]
    assert info["url"]
    assert isinstance(info["user_count"], int)
    assert isinstance(info["active_month"], int)


async def test_collect_server_info_listing_disabled(db, mock_valkey):
    """listing_enabled が false でも情報を収集できる。"""
    from app.services.server_listing_worker import _collect_server_info

    await _setup_admin(db)
    await _set_listing_settings(db, enabled=False)

    info = await _collect_server_info(db)
    assert info["listing_enabled"] is False
    assert info["name"] == "Test Server"


@patch("app.services.server_listing_worker.httpx.AsyncClient")
async def test_notify_listing_api(mock_client_cls):
    """_notify_listing_api が正しくPOSTリクエストを送信する。"""
    from app.services.server_listing_worker import _notify_listing_api

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = AsyncMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client_cls.return_value = mock_client

    payload = {"name": "Test", "url": "https://example.com"}
    await _notify_listing_api("https://directory.example.com/api/v1/servers", payload)

    mock_client.post.assert_called_once_with(
        "https://directory.example.com/api/v1/servers",
        json=payload,
    )


async def test_admin_settings_include_listing_fields(app_client, db, mock_valkey):
    """GET /api/v1/admin/settings がサーバーリスト設定フィールドを返す。"""
    from tests.test_api_admin import make_admin

    await make_admin(db, mock_valkey, app_client)

    resp = await app_client.get("/api/v1/admin/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "server_listing_enabled" in data
    assert "server_listing_url" in data
    assert data["server_listing_enabled"] is False
    assert data["server_listing_url"] is None


async def test_admin_settings_update_listing(app_client, db, mock_valkey):
    """PATCH /api/v1/admin/settings でサーバーリスト設定を更新できる。"""
    from tests.test_api_admin import make_admin

    await make_admin(db, mock_valkey, app_client)

    resp = await app_client.patch(
        "/api/v1/admin/settings",
        json={
            "server_listing_enabled": True,
            "server_listing_url": "https://directory.example.com/api/v1/servers",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["server_listing_enabled"] is True
    assert data["server_listing_url"] == "https://directory.example.com/api/v1/servers"
