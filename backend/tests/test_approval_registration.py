"""Tests for approval-based registration mode."""

from unittest.mock import AsyncMock

from app.services.server_settings_service import set_setting
from app.services.user_service import create_user


# --- Service layer tests ---


async def test_create_user_with_pending_status(db, mock_valkey):
    """User can be created with approval_status='pending'."""
    user = await create_user(
        db,
        "penduser",
        "pend@test.com",
        "password1234",
        approval_status="pending",
        registration_reason="I love cats!",
    )
    assert user.approval_status == "pending"
    assert user.registration_reason == "I love cats!"


async def test_create_user_default_approved(db, mock_valkey):
    """Default user creation has approval_status='approved'."""
    user = await create_user(db, "appruser", "appr@test.com", "password1234")
    assert user.approval_status == "approved"
    assert user.registration_reason is None


# --- Registration API tests ---


async def test_register_approval_mode(app_client, db, mock_valkey):
    """Registration in approval mode creates pending user."""
    await set_setting(db, "registration_mode", "approval")
    await db.commit()

    resp = await app_client.post(
        "/api/v1/accounts",
        json={
            "username": "newappr",
            "email": "newappr@test.com",
            "password": "password1234",
            "reason": "I want to join!",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "newappr"


async def test_register_approval_mode_requires_reason(app_client, db, mock_valkey):
    """Registration in approval mode fails without reason."""
    await set_setting(db, "registration_mode", "approval")
    await db.commit()

    resp = await app_client.post(
        "/api/v1/accounts",
        json={
            "username": "noreason",
            "email": "noreason@test.com",
            "password": "password1234",
        },
    )
    assert resp.status_code == 422
    assert "motivation" in resp.json()["detail"].lower()


async def test_register_open_mode_ignores_reason(app_client, db, mock_valkey):
    """In open mode, reason field is ignored."""
    await set_setting(db, "registration_mode", "open")
    await db.commit()

    resp = await app_client.post(
        "/api/v1/accounts",
        json={
            "username": "openuser",
            "email": "openuser@test.com",
            "password": "password1234",
            "reason": "Some reason",
        },
    )
    assert resp.status_code == 201


# --- Login blocking tests ---


async def test_login_blocked_for_pending_user(app_client, db, mock_valkey):
    """Pending user cannot log in."""
    await create_user(
        db,
        "blocked",
        "blocked@test.com",
        "password1234",
        approval_status="pending",
        registration_reason="test",
    )

    resp = await app_client.post(
        "/api/v1/auth/login",
        json={
            "username": "blocked",
            "password": "password1234",
        },
    )
    assert resp.status_code == 403
    assert "pending" in resp.json()["detail"].lower()


async def test_login_allowed_for_approved_user(app_client, db, mock_valkey):
    """Approved user can log in normally."""
    await create_user(db, "okuser", "okuser@test.com", "password1234")

    mock_valkey.set = AsyncMock()
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={
            "username": "okuser",
            "password": "password1234",
        },
    )
    assert resp.status_code == 200


# --- Admin approval/rejection API tests ---


async def _make_staff(db, mock_valkey, app_client, username="appr_admin", role="admin"):
    admin = await create_user(db, username, f"{username}@test.com", "password1234", role=role)
    mock_valkey.get = AsyncMock(return_value=str(admin.id))
    app_client.cookies.set("nekonoverse_session", "test-session-id")
    return admin


async def test_list_pending_registrations(app_client, db, mock_valkey):
    """Admin can list pending registrations."""
    await _make_staff(db, mock_valkey, app_client)

    # 承認待ちユーザーを作成
    await create_user(
        db,
        "pending1",
        "pending1@test.com",
        "password1234",
        approval_status="pending",
        registration_reason="Reason 1",
    )
    await create_user(
        db,
        "pending2",
        "pending2@test.com",
        "password1234",
        approval_status="pending",
        registration_reason="Reason 2",
    )

    resp = await app_client.get("/api/v1/admin/registrations")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["reason"] == "Reason 1"
    assert data[1]["reason"] == "Reason 2"


async def test_list_pending_excludes_approved(app_client, db, mock_valkey):
    """Listing only shows pending users, not approved ones."""
    await _make_staff(db, mock_valkey, app_client)

    await create_user(
        db,
        "aprvd",
        "aprvd@test.com",
        "password1234",
        approval_status="approved",
    )
    await create_user(
        db,
        "pndng",
        "pndng@test.com",
        "password1234",
        approval_status="pending",
        registration_reason="test",
    )

    resp = await app_client.get("/api/v1/admin/registrations")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["username"] == "pndng"


async def test_approve_registration(app_client, db, mock_valkey):
    """Admin can approve a pending user."""
    await _make_staff(db, mock_valkey, app_client)

    pending_user = await create_user(
        db,
        "toapprove",
        "toapprove@test.com",
        "password1234",
        approval_status="pending",
        registration_reason="Please!",
    )

    resp = await app_client.post(f"/api/v1/admin/registrations/{pending_user.id}/approve")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # 承認されたことを確認
    await db.refresh(pending_user)
    assert pending_user.approval_status == "approved"


async def test_approve_already_approved_fails(app_client, db, mock_valkey):
    """Cannot approve a user that is already approved."""
    await _make_staff(db, mock_valkey, app_client)

    user = await create_user(db, "alreadyok", "alreadyok@test.com", "password1234")

    resp = await app_client.post(f"/api/v1/admin/registrations/{user.id}/approve")
    assert resp.status_code == 422


async def test_reject_registration(app_client, db, mock_valkey):
    """Admin can reject a pending user, which deletes the user."""
    await _make_staff(db, mock_valkey, app_client)

    pending_user = await create_user(
        db,
        "toreject",
        "toreject@test.com",
        "password1234",
        approval_status="pending",
        registration_reason="Not a cat",
    )
    user_id = pending_user.id

    resp = await app_client.post(f"/api/v1/admin/registrations/{user_id}/reject")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # ユーザーが削除されたことを確認
    from sqlalchemy import select
    from app.models.user import User

    result = await db.execute(select(User).where(User.id == user_id))
    assert result.scalar_one_or_none() is None


async def test_reject_already_approved_fails(app_client, db, mock_valkey):
    """Cannot reject a user that is already approved."""
    await _make_staff(db, mock_valkey, app_client)

    user = await create_user(db, "cantreject", "cantreject@test.com", "password1234")

    resp = await app_client.post(f"/api/v1/admin/registrations/{user.id}/reject")
    assert resp.status_code == 422


async def test_approved_user_can_login_after_approval(app_client, db, mock_valkey):
    """User who was pending and then approved can log in."""
    admin = await _make_staff(db, mock_valkey, app_client)

    pending_user = await create_user(
        db,
        "willlogin",
        "willlogin@test.com",
        "password1234",
        approval_status="pending",
        registration_reason="I'm a cat!",
    )

    # 承認
    await app_client.post(f"/api/v1/admin/registrations/{pending_user.id}/approve")

    # ログイン試行
    mock_valkey.get = AsyncMock(return_value=None)
    app_client.cookies.clear()
    mock_valkey.set = AsyncMock()

    resp = await app_client.post(
        "/api/v1/auth/login",
        json={
            "username": "willlogin",
            "password": "password1234",
        },
    )
    assert resp.status_code == 200


# --- Settings API test ---


async def test_settings_accept_approval_mode(app_client, db, mock_valkey):
    """Admin settings accept 'approval' as registration_mode."""
    await _make_staff(db, mock_valkey, app_client)

    resp = await app_client.patch(
        "/api/v1/admin/settings",
        json={"registration_mode": "approval"},
    )
    assert resp.status_code == 200
    assert resp.json()["registration_mode"] == "approval"


async def test_instance_returns_approval_mode(app_client, db, mock_valkey):
    """Instance endpoint returns approval as registration_mode."""
    await set_setting(db, "registration_mode", "approval")
    await db.commit()

    resp = await app_client.get("/api/v1/instance")
    assert resp.status_code == 200
    data = resp.json()
    assert data["registration_mode"] == "approval"
    # 承認制も登録自体は受け付けているのでregistrations=True
    assert data["registrations"] is True


# --- Full flow integration test ---


async def test_full_approval_flow(app_client, db, mock_valkey):
    """Full flow: register -> pending -> login fails -> approve -> login works."""
    # 承認制モードに設定
    await set_setting(db, "registration_mode", "approval")
    await db.commit()

    # 1. 登録
    reg = await app_client.post(
        "/api/v1/accounts",
        json={
            "username": "fullflow",
            "email": "fullflow@test.com",
            "password": "password1234",
            "reason": "Big cat fan!",
        },
    )
    assert reg.status_code == 201
    user_id = reg.json()["id"]

    # 2. ログイン失敗 (承認待ち)
    login_resp = await app_client.post(
        "/api/v1/auth/login",
        json={
            "username": "fullflow",
            "password": "password1234",
        },
    )
    assert login_resp.status_code == 403

    # 3. 管理者がログインして承認
    admin = await create_user(db, "flowadmin", "flowadmin@test.com", "password1234", role="admin")
    mock_valkey.get = AsyncMock(return_value=str(admin.id))
    app_client.cookies.set("nekonoverse_session", "test-session-id")

    approve_resp = await app_client.post(f"/api/v1/admin/registrations/{user_id}/approve")
    assert approve_resp.status_code == 200

    # 4. ログイン成功
    mock_valkey.get = AsyncMock(return_value=None)
    app_client.cookies.clear()
    mock_valkey.set = AsyncMock()

    login_resp2 = await app_client.post(
        "/api/v1/auth/login",
        json={
            "username": "fullflow",
            "password": "password1234",
        },
    )
    assert login_resp2.status_code == 200


# --- Mode change auto-resolve tests ---


async def test_mode_change_to_open_approves_pending(app_client, db, mock_valkey):
    """Switching to open mode auto-approves all pending users."""
    await _make_staff(db, mock_valkey, app_client, "mc_admin1")

    await create_user(
        db,
        "mc_pend1",
        "mc_pend1@test.com",
        "password1234",
        approval_status="pending",
        registration_reason="test",
    )
    await create_user(
        db,
        "mc_pend2",
        "mc_pend2@test.com",
        "password1234",
        approval_status="pending",
        registration_reason="test",
    )

    resp = await app_client.patch(
        "/api/v1/admin/settings",
        json={"registration_mode": "open"},
    )
    assert resp.status_code == 200

    # pendingユーザーが全員承認されたことを確認
    list_resp = await app_client.get("/api/v1/admin/registrations")
    assert len(list_resp.json()) == 0

    # 承認されたユーザーがログインできる
    mock_valkey.get = AsyncMock(return_value=None)
    app_client.cookies.clear()
    mock_valkey.set = AsyncMock()

    login_resp = await app_client.post(
        "/api/v1/auth/login",
        json={"username": "mc_pend1", "password": "password1234"},
    )
    assert login_resp.status_code == 200


async def test_mode_change_to_closed_rejects_pending(app_client, db, mock_valkey):
    """Switching to closed mode auto-rejects (deletes) all pending users."""
    await _make_staff(db, mock_valkey, app_client, "mc_admin2")

    pend = await create_user(
        db,
        "mc_del1",
        "mc_del1@test.com",
        "password1234",
        approval_status="pending",
        registration_reason="test",
    )
    user_id = pend.id

    resp = await app_client.patch(
        "/api/v1/admin/settings",
        json={"registration_mode": "closed"},
    )
    assert resp.status_code == 200

    # ユーザーが削除されたことを確認
    from sqlalchemy import select as sa_select

    from app.models.user import User

    result = await db.execute(sa_select(User).where(User.id == user_id))
    assert result.scalar_one_or_none() is None


async def test_mode_change_to_invite_rejects_pending(app_client, db, mock_valkey):
    """Switching to invite mode auto-rejects (deletes) all pending users."""
    await _make_staff(db, mock_valkey, app_client, "mc_admin3")

    await create_user(
        db,
        "mc_inv1",
        "mc_inv1@test.com",
        "password1234",
        approval_status="pending",
        registration_reason="test",
    )

    resp = await app_client.patch(
        "/api/v1/admin/settings",
        json={"registration_mode": "invite"},
    )
    assert resp.status_code == 200

    list_resp = await app_client.get("/api/v1/admin/registrations")
    assert len(list_resp.json()) == 0
