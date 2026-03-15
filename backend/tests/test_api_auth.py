from io import BytesIO
from unittest.mock import AsyncMock, patch


async def test_register_success(app_client, mock_valkey):
    resp = await app_client.post("/api/v1/accounts", json={
        "username": "newuser", "email": "new@example.com", "password": "password1234"
    })
    assert resp.status_code == 201
    assert resp.json()["username"] == "newuser"


async def test_register_short_password(app_client, mock_valkey):
    resp = await app_client.post("/api/v1/accounts", json={
        "username": "newuser", "email": "new@example.com", "password": "short"
    })
    assert resp.status_code == 422


async def test_register_invalid_username(app_client, mock_valkey):
    resp = await app_client.post("/api/v1/accounts", json={
        "username": "bad user!", "email": "new@example.com", "password": "password1234"
    })
    assert resp.status_code == 422


async def test_login_success(app_client, test_user, mock_valkey):
    resp = await app_client.post("/api/v1/auth/login", json={
        "username": "testuser", "password": "password1234"
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    mock_valkey.set.assert_called()


async def test_login_wrong_password(app_client, test_user, mock_valkey):
    resp = await app_client.post("/api/v1/auth/login", json={
        "username": "testuser", "password": "wrongpassword"
    })
    assert resp.status_code == 401


async def test_login_nonexistent_user(app_client, mock_valkey):
    resp = await app_client.post("/api/v1/auth/login", json={
        "username": "nobody", "password": "password1234"
    })
    assert resp.status_code == 401


async def test_logout(app_client, mock_valkey):
    app_client.cookies.set("nekonoverse_session", "some-session-id")
    resp = await app_client.post("/api/v1/auth/logout")
    assert resp.status_code == 200
    mock_valkey.delete.assert_called()


async def test_verify_credentials_success(authed_client, test_user):
    resp = await authed_client.get("/api/v1/accounts/verify_credentials")
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "testuser"
    assert data["role"] == "user"


async def test_verify_credentials_mastodon_compat(authed_client, test_user):
    """verify_credentials returns Mastodon CredentialAccount fields."""
    resp = await authed_client.get("/api/v1/accounts/verify_credentials")
    assert resp.status_code == 200
    data = resp.json()
    # Mastodon required fields
    assert "email" in data
    assert "acct" in data
    assert data["acct"] == "testuser"
    assert "url" in data
    assert "source" in data
    assert "note" in data
    assert "emojis" in data
    assert isinstance(data["emojis"], list)
    assert "followers_count" in data
    assert "following_count" in data
    assert "statuses_count" in data
    assert isinstance(data["followers_count"], int)
    assert isinstance(data["source"], dict)
    assert "privacy" in data["source"]
    assert "note" in data["source"]
    assert "fields" in data["source"]
    # Mastodon avatar/header fields
    assert "avatar" in data
    assert "header" in data
    # Nekonoverse extensions still present
    assert "avatar_url" in data
    assert "avatar_focal" in data
    assert "role" in data
    assert "is_cat" in data
    assert "birthday" in data


async def test_verify_credentials_no_session(app_client, mock_valkey):
    resp = await app_client.get("/api/v1/accounts/verify_credentials")
    assert resp.status_code == 401


async def test_register_returns_role(app_client, mock_valkey):
    resp = await app_client.post("/api/v1/accounts", json={
        "username": "roleuser", "email": "role@example.com", "password": "password1234"
    })
    assert resp.status_code == 201
    assert resp.json()["role"] == "user"


# ── Case-insensitive username ──


async def test_register_normalizes_username(app_client, mock_valkey):
    resp = await app_client.post("/api/v1/accounts", json={
        "username": "CamelCase", "email": "camel@example.com", "password": "password1234"
    })
    assert resp.status_code == 201
    assert resp.json()["username"] == "camelcase"


async def test_login_case_insensitive(app_client, test_user, mock_valkey):
    resp = await app_client.post("/api/v1/auth/login", json={
        "username": "TestUser", "password": "password1234"
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ── Update display name ──


async def test_update_display_name(authed_client, test_user):
    resp = await authed_client.patch(
        "/api/v1/accounts/update_credentials",
        data={"display_name": "New Name"},
    )
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "New Name"


async def test_update_display_name_unauthenticated(app_client, mock_valkey):
    resp = await app_client.patch(
        "/api/v1/accounts/update_credentials",
        data={"display_name": "New Name"},
    )
    assert resp.status_code == 401


# ── Change password ──


async def test_change_password_success(authed_client, test_user):
    resp = await authed_client.post("/api/v1/auth/change_password", json={
        "current_password": "password1234", "new_password": "newpassword5678"
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


async def test_change_password_wrong_current(authed_client, test_user):
    resp = await authed_client.post("/api/v1/auth/change_password", json={
        "current_password": "wrongpassword", "new_password": "newpassword5678"
    })
    assert resp.status_code == 422


async def test_change_password_too_short(authed_client, test_user):
    resp = await authed_client.post("/api/v1/auth/change_password", json={
        "current_password": "password1234", "new_password": "short"
    })
    assert resp.status_code == 422


async def test_change_password_unauthenticated(app_client, mock_valkey):
    resp = await app_client.post("/api/v1/auth/change_password", json={
        "current_password": "password1234", "new_password": "newpassword5678"
    })
    assert resp.status_code == 401


# ── Avatar upload ──

PNG_1x1 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde"
)


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_update_avatar(mock_s3, authed_client, test_user):
    mock_s3.return_value = "etag"
    resp = await authed_client.patch(
        "/api/v1/accounts/update_credentials",
        files={"avatar": ("avatar.png", BytesIO(PNG_1x1), "image/png")},
    )
    assert resp.status_code == 200
    assert resp.json()["avatar_url"] is not None


# ── TOTP tests ──


async def test_totp_status_disabled(authed_client, test_user):
    resp = await authed_client.get("/api/v1/auth/totp/status")
    assert resp.status_code == 200
    assert resp.json()["totp_enabled"] is False


async def test_totp_setup(authed_client, test_user):
    resp = await authed_client.post(
        "/api/v1/auth/totp/setup", json={"password": "password1234"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "secret" in data
    assert "provisioning_uri" in data
    assert len(data["secret"]) == 32


async def test_totp_setup_already_enabled(authed_client, test_user, db):
    test_user.totp_enabled = True
    await db.flush()
    resp = await authed_client.post(
        "/api/v1/auth/totp/setup", json={"password": "password1234"},
    )
    assert resp.status_code == 400


async def test_totp_enable(authed_client, test_user, db):
    setup_resp = await authed_client.post(
        "/api/v1/auth/totp/setup", json={"password": "password1234"},
    )
    secret = setup_resp.json()["secret"]

    import pyotp
    code = pyotp.TOTP(secret).now()

    resp = await authed_client.post("/api/v1/auth/totp/enable", json={"code": code})
    assert resp.status_code == 200
    data = resp.json()
    assert "recovery_codes" in data
    assert len(data["recovery_codes"]) > 0


async def test_totp_enable_invalid_code(authed_client, test_user, db):
    await authed_client.post(
        "/api/v1/auth/totp/setup", json={"password": "password1234"},
    )
    resp = await authed_client.post("/api/v1/auth/totp/enable", json={"code": "000000"})
    assert resp.status_code == 400


async def test_totp_enable_no_setup(authed_client, test_user, db):
    resp = await authed_client.post("/api/v1/auth/totp/enable", json={"code": "123456"})
    assert resp.status_code == 400


async def test_totp_disable(authed_client, test_user, db):
    setup_resp = await authed_client.post(
        "/api/v1/auth/totp/setup", json={"password": "password1234"},
    )
    secret = setup_resp.json()["secret"]
    import pyotp
    code = pyotp.TOTP(secret).now()
    await authed_client.post("/api/v1/auth/totp/enable", json={"code": code})

    resp = await authed_client.post("/api/v1/auth/totp/disable", json={
        "password": "password1234"
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


async def test_totp_disable_wrong_password(authed_client, test_user, db):
    setup_resp = await authed_client.post(
        "/api/v1/auth/totp/setup", json={"password": "password1234"},
    )
    secret = setup_resp.json()["secret"]
    import pyotp
    code = pyotp.TOTP(secret).now()
    await authed_client.post("/api/v1/auth/totp/enable", json={"code": code})

    resp = await authed_client.post("/api/v1/auth/totp/disable", json={
        "password": "wrongpassword"
    })
    assert resp.status_code == 400


async def test_totp_disable_not_enabled(authed_client, test_user):
    resp = await authed_client.post("/api/v1/auth/totp/disable", json={
        "password": "password1234"
    })
    assert resp.status_code == 400


async def test_totp_verify(app_client, test_user, db, mock_valkey):
    """Full TOTP login flow: login -> requires_totp -> verify."""
    import pyotp

    from app.services.totp_service import (
        encrypt_secret,
        generate_recovery_codes,
        generate_totp_secret,
        hash_recovery_codes,
    )

    secret = generate_totp_secret()
    test_user.totp_secret = encrypt_secret(secret)
    test_user.totp_enabled = True
    recovery = generate_recovery_codes()
    test_user.totp_recovery_codes = hash_recovery_codes(recovery)
    await db.flush()

    login_resp = await app_client.post("/api/v1/auth/login", json={
        "username": "testuser", "password": "password1234"
    })
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    assert login_data["requires_totp"] is True
    totp_token = login_data["totp_token"]

    # valkeyのgetが呼ばれた時にユーザーIDを返すようにモック
    mock_valkey.get = AsyncMock(
        side_effect=lambda key: str(test_user.id) if "totp_pending:" in key else None,
    )

    code = pyotp.TOTP(secret).now()
    resp = await app_client.post("/api/v1/auth/totp/verify", json={
        "totp_token": totp_token,
        "code": code,
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


async def test_totp_verify_invalid_token(app_client, mock_valkey):
    mock_valkey.get = AsyncMock(return_value=None)
    resp = await app_client.post("/api/v1/auth/totp/verify", json={
        "totp_token": "invalid-token",
        "code": "123456",
    })
    assert resp.status_code == 401


async def test_totp_status_unauthenticated(app_client, mock_valkey):
    resp = await app_client.get("/api/v1/auth/totp/status")
    assert resp.status_code == 401


async def test_totp_setup_unauthenticated(app_client, mock_valkey):
    resp = await app_client.post(
        "/api/v1/auth/totp/setup", json={"password": "anything"},
    )
    assert resp.status_code == 401
