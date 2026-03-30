"""Tests for invite code API endpoints."""

import uuid
from unittest.mock import AsyncMock, patch


@patch(
    "app.services.server_settings_service.get_setting",
    new_callable=AsyncMock,
    return_value="user",
)
async def test_create_invite(mock_setting, authed_client, test_user, db, seed_roles):
    """POST /api/v1/invites creates an invitation code."""
    resp = await authed_client.post("/api/v1/invites", json={"max_uses": 1})
    assert resp.status_code == 201
    data = resp.json()
    assert "code" in data
    assert data["created_by"] == "testuser"
    assert data["max_uses"] == 1
    assert data["use_count"] == 0


async def test_create_invite_forbidden(authed_client, test_user, db, seed_roles):
    """POST /api/v1/invites returns 403 when user lacks sufficient role.

    Default role setting is "admin", so a normal user cannot create invites.
    """
    resp = await authed_client.post("/api/v1/invites", json={"max_uses": 1})
    assert resp.status_code == 403


@patch(
    "app.services.server_settings_service.get_setting",
    new_callable=AsyncMock,
    return_value="user",
)
async def test_list_invites(mock_setting, authed_client, test_user, db, seed_roles):
    """GET /api/v1/invites lists invites created by the current user."""
    # まず招待コードを作成
    create_resp = await authed_client.post("/api/v1/invites", json={"max_uses": 5})
    assert create_resp.status_code == 201
    code = create_resp.json()["code"]

    resp = await authed_client.get("/api/v1/invites")
    assert resp.status_code == 200
    data = resp.json()
    codes = [inv["code"] for inv in data]
    assert code in codes


@patch(
    "app.services.server_settings_service.get_setting",
    new_callable=AsyncMock,
    return_value="user",
)
async def test_revoke_invite(mock_setting, authed_client, test_user, db, seed_roles):
    """DELETE /api/v1/invites/{code} revokes the invite."""
    create_resp = await authed_client.post("/api/v1/invites")
    assert create_resp.status_code == 201
    code = create_resp.json()["code"]

    resp = await authed_client.delete(f"/api/v1/invites/{code}")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # 削除後にリストに表示されないことを確認
    list_resp = await authed_client.get("/api/v1/invites")
    codes = [inv["code"] for inv in list_resp.json()]
    assert code not in codes


async def test_revoke_invite_not_found(authed_client, test_user, db):
    """DELETE /api/v1/invites/{code} returns 404 for non-existent code."""
    resp = await authed_client.delete(f"/api/v1/invites/{uuid.uuid4().hex}")
    assert resp.status_code == 404


async def test_invite_unauthenticated(app_client, db):
    """Unauthenticated requests to invite endpoints are rejected."""
    endpoints = [
        ("POST", "/api/v1/invites"),
        ("GET", "/api/v1/invites"),
        ("DELETE", "/api/v1/invites/fakecode"),
    ]
    for method, path in endpoints:
        resp = await app_client.request(method, path)
        assert resp.status_code in (401, 403), (
            f"{method} {path} returned {resp.status_code}, expected 401/403"
        )
