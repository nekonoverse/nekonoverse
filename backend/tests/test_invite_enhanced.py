"""Tests for enhanced invitation codes: multi-use and expiration."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

from app.services.invitation_service import (
    create_invitation,
    delete_invitation,
    redeem_invitation,
    validate_invitation_code,
)


async def test_create_single_use(db, mock_valkey, test_user):
    """Default: single-use code."""
    invite = await create_invitation(db, test_user)
    assert invite.max_uses == 1
    assert invite.use_count == 0
    assert invite.expires_at is None


async def test_create_multi_use(db, mock_valkey, test_user):
    """Create a code usable N times."""
    invite = await create_invitation(db, test_user, max_uses=5)
    assert invite.max_uses == 5
    assert invite.use_count == 0


async def test_create_unlimited(db, mock_valkey, test_user):
    """Create a code with unlimited uses."""
    invite = await create_invitation(db, test_user, max_uses=None)
    assert invite.max_uses is None


async def test_create_with_expiry(db, mock_valkey, test_user):
    """Create a code that expires in N days."""
    invite = await create_invitation(db, test_user, expires_in_days=7)
    assert invite.expires_at is not None
    delta = invite.expires_at - datetime.now(timezone.utc)
    assert 6 < delta.total_seconds() / 86400 < 8


async def test_create_multi_use_with_expiry(db, mock_valkey, test_user):
    """Create a code with both usage limit and expiration."""
    invite = await create_invitation(db, test_user, max_uses=3, expires_in_days=30)
    assert invite.max_uses == 3
    assert invite.expires_at is not None


async def test_multi_use_redeem_increments(db, mock_valkey, test_user):
    """Redeeming increments use_count."""
    invite = await create_invitation(db, test_user, max_uses=3)
    # 1回目の使用
    await redeem_invitation(db, invite, test_user)
    assert invite.use_count == 1
    # まだ有効
    valid = await validate_invitation_code(db, invite.code)
    assert valid is not None


async def test_multi_use_exhausted(db, mock_valkey, test_user):
    """Code becomes invalid after max_uses reached."""
    invite = await create_invitation(db, test_user, max_uses=2)
    await redeem_invitation(db, invite, test_user)
    await redeem_invitation(db, invite, test_user)
    assert invite.use_count == 2
    # 上限到達 → 無効
    valid = await validate_invitation_code(db, invite.code)
    assert valid is None


async def test_unlimited_never_exhausted(db, mock_valkey, test_user):
    """Unlimited code remains valid after many uses."""
    invite = await create_invitation(db, test_user, max_uses=None)
    for _ in range(10):
        await redeem_invitation(db, invite, test_user)
    assert invite.use_count == 10
    valid = await validate_invitation_code(db, invite.code)
    assert valid is not None


async def test_expired_code_invalid(db, mock_valkey, test_user):
    """Expired code is invalid regardless of use_count."""
    invite = await create_invitation(db, test_user, max_uses=None, expires_in_days=1)
    # 有効期限を過去に設定
    invite.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db.flush()
    valid = await validate_invitation_code(db, invite.code)
    assert valid is None


async def test_multi_use_single_use_compat(db, mock_valkey, test_user):
    """Single-use code (max_uses=1) is invalid after one use."""
    invite = await create_invitation(db, test_user, max_uses=1)
    await redeem_invitation(db, invite, test_user)
    valid = await validate_invitation_code(db, invite.code)
    assert valid is None


async def test_expires_in_days_zero_ignored(db, mock_valkey, test_user):
    """expires_in_days=0 does not set an expiration."""
    invite = await create_invitation(db, test_user, expires_in_days=0)
    assert invite.expires_at is None


async def test_expires_in_days_negative_ignored(db, mock_valkey, test_user):
    """Negative expires_in_days does not set an expiration."""
    invite = await create_invitation(db, test_user, expires_in_days=-1)
    assert invite.expires_at is None


async def test_delete_by_admin(db, mock_valkey, test_user):
    """Admin can delete any invite, not just their own."""
    from app.services.user_service import create_user

    admin = await create_user(db, "deladmin", "deladmin@test.com", "pw12345678", role="admin")
    invite = await create_invitation(db, test_user)
    result = await delete_invitation(db, invite.code, admin)
    assert result is True


async def test_multi_use_used_by_tracks_last(db, mock_valkey, test_user):
    """used_by_id and used_at are updated on each redemption."""
    from app.services.user_service import create_user

    invite = await create_invitation(db, test_user, max_uses=5)
    user2 = await create_user(db, "invuser2", "invuser2@test.com", "pw12345678")
    await redeem_invitation(db, invite, test_user)
    assert invite.used_by_id == test_user.id
    await redeem_invitation(db, invite, user2)
    # 最後に使用したユーザーが記録される
    assert invite.used_by_id == user2.id
    assert invite.use_count == 2


async def test_expired_multi_use_not_exhausted(db, mock_valkey, test_user):
    """Multi-use code that expired before reaching max_uses is invalid."""
    invite = await create_invitation(db, test_user, max_uses=10, expires_in_days=1)
    await redeem_invitation(db, invite, test_user)
    assert invite.use_count == 1
    # 期限を過去に設定
    invite.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db.flush()
    valid = await validate_invitation_code(db, invite.code)
    assert valid is None


# --- API tests for enhanced invite parameters ---


async def _make_admin(db, mock_valkey, app_client, username="enh_admin"):
    from app.services.user_service import create_user

    user = await create_user(db, username, f"{username}@test.com", "password1234", role="admin")
    mock_valkey.get = AsyncMock(return_value=str(user.id))
    app_client.cookies.set("nekonoverse_session", "test-session-id")
    return user


async def test_api_create_with_max_uses(app_client, db, mock_valkey):
    """POST /api/v1/invites with max_uses parameter."""
    await _make_admin(db, mock_valkey, app_client)
    resp = await app_client.post("/api/v1/invites", json={"max_uses": 10})
    assert resp.status_code == 201
    data = resp.json()
    assert data["max_uses"] == 10
    assert data["use_count"] == 0


async def test_api_create_unlimited(app_client, db, mock_valkey):
    """POST /api/v1/invites with max_uses=null creates unlimited code."""
    await _make_admin(db, mock_valkey, app_client)
    resp = await app_client.post("/api/v1/invites", json={"max_uses": None})
    assert resp.status_code == 201
    data = resp.json()
    assert data["max_uses"] is None


async def test_api_create_with_expiry(app_client, db, mock_valkey):
    """POST /api/v1/invites with expires_in_days parameter."""
    await _make_admin(db, mock_valkey, app_client)
    resp = await app_client.post("/api/v1/invites", json={"expires_in_days": 7})
    assert resp.status_code == 201
    data = resp.json()
    assert data["expires_at"] is not None


async def test_api_create_default_single_use(app_client, db, mock_valkey):
    """POST /api/v1/invites without body creates single-use code."""
    await _make_admin(db, mock_valkey, app_client)
    resp = await app_client.post("/api/v1/invites")
    assert resp.status_code == 201
    data = resp.json()
    assert data["max_uses"] == 1
    assert data["use_count"] == 0
    assert data["expires_at"] is None


async def test_api_list_includes_enhanced_fields(app_client, db, mock_valkey):
    """GET /api/v1/invites returns max_uses and use_count."""
    await _make_admin(db, mock_valkey, app_client)
    await app_client.post("/api/v1/invites", json={"max_uses": 5, "expires_in_days": 30})
    resp = await app_client.get("/api/v1/invites")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    inv = data[0]
    assert "max_uses" in inv
    assert "use_count" in inv
    assert inv["max_uses"] == 5
    assert inv["use_count"] == 0
    assert inv["expires_at"] is not None


async def test_register_multi_use_invite_twice(app_client, db, mock_valkey):
    """Multi-use invite can be used for multiple registrations."""
    from app.services.server_settings_service import set_setting

    await set_setting(db, "registration_mode", "invite")
    await db.commit()

    await _make_admin(db, mock_valkey, app_client, "mu_admin")
    resp = await app_client.post("/api/v1/invites", json={"max_uses": 3})
    code = resp.json()["code"]

    mock_valkey.get = AsyncMock(return_value=None)
    app_client.cookies.clear()

    # 1回目の登録
    r1 = await app_client.post(
        "/api/v1/accounts",
        json={
            "username": "muuser1",
            "email": "mu1@test.com",
            "password": "password1234",
            "invite_code": code,
        },
    )
    assert r1.status_code == 201

    # 2回目の登録 — 同じコードで成功
    r2 = await app_client.post(
        "/api/v1/accounts",
        json={
            "username": "muuser2",
            "email": "mu2@test.com",
            "password": "password1234",
            "invite_code": code,
        },
    )
    assert r2.status_code == 201


async def test_register_exhausted_multi_use_rejected(app_client, db, mock_valkey):
    """Exhausted multi-use invite is rejected for registration."""
    from app.services.server_settings_service import set_setting

    await set_setting(db, "registration_mode", "invite")
    await db.commit()

    await _make_admin(db, mock_valkey, app_client, "ex_admin")
    resp = await app_client.post("/api/v1/invites", json={"max_uses": 1})
    code = resp.json()["code"]

    mock_valkey.get = AsyncMock(return_value=None)
    app_client.cookies.clear()

    # 1回目: 成功
    r1 = await app_client.post(
        "/api/v1/accounts",
        json={
            "username": "exuser1",
            "email": "ex1@test.com",
            "password": "password1234",
            "invite_code": code,
        },
    )
    assert r1.status_code == 201

    # 2回目: 使い切り → 拒否
    r2 = await app_client.post(
        "/api/v1/accounts",
        json={
            "username": "exuser2",
            "email": "ex2@test.com",
            "password": "password1234",
            "invite_code": code,
        },
    )
    assert r2.status_code == 422


async def test_register_expired_invite_rejected(app_client, db, mock_valkey):
    """Expired invite is rejected for registration."""
    from app.services.server_settings_service import set_setting

    await set_setting(db, "registration_mode", "invite")
    await db.commit()

    await _make_admin(db, mock_valkey, app_client, "exp_admin")
    resp = await app_client.post("/api/v1/invites", json={"expires_in_days": 1})
    code = resp.json()["code"]

    # 期限を過去にする
    from sqlalchemy import select

    from app.models.invitation_code import InvitationCode

    result = await db.execute(select(InvitationCode).where(InvitationCode.code == code))
    invite = result.scalar_one()
    invite.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db.commit()

    mock_valkey.get = AsyncMock(return_value=None)
    app_client.cookies.clear()

    r = await app_client.post(
        "/api/v1/accounts",
        json={
            "username": "expuser",
            "email": "expuser@test.com",
            "password": "password1234",
            "invite_code": code,
        },
    )
    assert r.status_code == 422
