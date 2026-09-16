"""管理 API のアクセス制御 (OAuth スコープ・権限なしロール) の回帰テスト。"""

import hashlib
from unittest.mock import AsyncMock

import pytest

from app.models.oauth import OAuthApplication, OAuthToken
from app.models.role import Role

pytestmark = pytest.mark.usefixtures("seed_roles")


async def _make_user(db, username: str, role: str):
    from app.services.user_service import create_user

    user = await create_user(db, username, f"{username}@example.com", "password1234")
    user.role = role
    await db.flush()
    return user


async def _bearer(db, user, scopes: str) -> dict[str, str]:
    app = OAuthApplication(
        name=f"app-{scopes}",
        client_id=f"cid-{user.id}-{scopes}",
        client_secret="x",
        redirect_uris="urn:ietf:wg:oauth:2.0:oob",
        scopes=scopes,
    )
    db.add(app)
    await db.flush()
    raw = f"token-{user.id}-{scopes}"
    db.add(
        OAuthToken(
            access_token=hashlib.sha256(raw.encode()).hexdigest(),
            scopes=scopes,
            application_id=app.id,
            user_id=user.id,
        )
    )
    await db.flush()
    return {"Authorization": f"Bearer {raw}"}


async def test_admin_api_requires_admin_read_scope(app_client, db, mock_valkey):
    admin = await _make_user(db, "scopeadmin", "admin")

    resp = await app_client.get(
        "/api/v1/admin/settings", headers=await _bearer(db, admin, "read write")
    )
    assert resp.status_code == 403

    resp = await app_client.get(
        "/api/v1/admin/settings", headers=await _bearer(db, admin, "read admin:read")
    )
    assert resp.status_code == 200


async def test_admin_write_requires_admin_write_scope(app_client, db, mock_valkey, test_user):
    admin = await _make_user(db, "scopeadmin2", "admin")

    headers = await _bearer(db, admin, "read write admin:read")
    resp = await app_client.post(f"/api/v1/admin/users/{test_user.id}/silence", headers=headers)
    assert resp.status_code == 403
    await db.refresh(test_user.actor)
    assert not test_user.actor.is_silenced

    headers = await _bearer(db, admin, "read write admin:read admin:write")
    resp = await app_client.post(f"/api/v1/admin/users/{test_user.id}/silence", headers=headers)
    assert resp.status_code == 200


async def test_moderation_log_requires_some_permission(app_client, db, mock_valkey):
    db.add(
        Role(
            name="helper",
            display_name="Helper",
            permissions={},
            is_admin=False,
            quota_bytes=0,
            priority=10,
        )
    )
    helper = await _make_user(db, "helperuser", "helper")
    moderator = await _make_user(db, "moduser2", "moderator")
    app_client.cookies.set("nekonoverse_session", "sid")

    mock_valkey.get = AsyncMock(return_value=str(helper.id))
    resp = await app_client.get("/api/v1/admin/log")
    assert resp.status_code == 403

    mock_valkey.get = AsyncMock(return_value=str(moderator.id))
    resp = await app_client.get("/api/v1/admin/log")
    assert resp.status_code == 200
