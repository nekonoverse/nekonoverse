import uuid
from unittest.mock import AsyncMock

import pyotp

# ── TOTP service unit tests ──


def test_encrypt_decrypt_secret():
    from app.services.totp_service import decrypt_secret, encrypt_secret

    secret = "JBSWY3DPEHPK3PXP"
    encrypted = encrypt_secret(secret)
    assert encrypted != secret
    assert decrypt_secret(encrypted) == secret


def test_generate_totp_secret():
    from app.services.totp_service import generate_totp_secret

    secret = generate_totp_secret()
    assert len(secret) == 32  # pyotp default base32 length


def test_generate_provisioning_uri():
    from app.services.totp_service import generate_provisioning_uri

    uri = generate_provisioning_uri(
        "JBSWY3DPEHPK3PXP", "testuser", "TestIssuer",
    )
    assert "otpauth://totp/" in uri
    assert "testuser" in uri
    assert "TestIssuer" in uri


def test_verify_totp_code_valid():
    from app.services.totp_service import verify_totp_code

    secret = "JBSWY3DPEHPK3PXP"
    totp = pyotp.TOTP(secret)
    code = totp.now()
    assert verify_totp_code(secret, code) is True


def test_verify_totp_code_invalid():
    from app.services.totp_service import verify_totp_code

    assert verify_totp_code("JBSWY3DPEHPK3PXP", "000000") is False


def test_generate_recovery_codes():
    from app.services.totp_service import generate_recovery_codes

    codes = generate_recovery_codes(8)
    assert len(codes) == 8
    for code in codes:
        assert "-" in code
        assert len(code) == 11  # 5 + 1 + 5


def test_hash_and_verify_recovery_code():
    from app.services.totp_service import (
        hash_recovery_codes,
        verify_recovery_code,
    )

    codes = ["abc12-xyz34", "def56-uvw78"]
    hashed = hash_recovery_codes(codes)
    assert len(hashed) == 2

    valid, remaining = verify_recovery_code("abc12-xyz34", hashed)
    assert valid is True
    assert len(remaining) == 1

    valid2, remaining2 = verify_recovery_code("wrong-code0", remaining)
    assert valid2 is False
    assert len(remaining2) == 1


# ── API endpoint tests ──


async def test_totp_setup(authed_client, test_user):
    resp = await authed_client.post(
        "/api/v1/auth/totp/setup", json={"password": "password1234"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "secret" in data
    assert "provisioning_uri" in data
    assert "otpauth://totp/" in data["provisioning_uri"]


async def test_totp_setup_already_enabled(authed_client, test_user, db):
    test_user.totp_enabled = True
    await db.commit()
    resp = await authed_client.post(
        "/api/v1/auth/totp/setup", json={"password": "password1234"},
    )
    assert resp.status_code == 400


async def test_totp_enable_success(authed_client, test_user, db):
    from app.services.totp_service import encrypt_secret

    secret = "JBSWY3DPEHPK3PXP"
    test_user.totp_secret = encrypt_secret(secret)
    await db.commit()

    totp = pyotp.TOTP(secret)
    code = totp.now()

    resp = await authed_client.post(
        "/api/v1/auth/totp/enable", json={"code": code},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "recovery_codes" in data
    assert len(data["recovery_codes"]) == 8


async def test_totp_enable_invalid_code(authed_client, test_user, db):
    from app.services.totp_service import encrypt_secret

    secret = "JBSWY3DPEHPK3PXP"
    test_user.totp_secret = encrypt_secret(secret)
    await db.commit()

    resp = await authed_client.post(
        "/api/v1/auth/totp/enable", json={"code": "000000"},
    )
    assert resp.status_code == 400


async def test_totp_enable_no_setup(authed_client, test_user):
    resp = await authed_client.post(
        "/api/v1/auth/totp/enable", json={"code": "123456"},
    )
    assert resp.status_code == 400


async def test_totp_disable_success(authed_client, test_user, db):
    from app.services.totp_service import encrypt_secret

    test_user.totp_enabled = True
    test_user.totp_secret = encrypt_secret("JBSWY3DPEHPK3PXP")
    test_user.totp_recovery_codes = ["hash1", "hash2"]
    await db.commit()

    resp = await authed_client.post(
        "/api/v1/auth/totp/disable", json={"password": "password1234"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


async def test_totp_disable_wrong_password(authed_client, test_user, db):
    from app.services.totp_service import encrypt_secret

    test_user.totp_enabled = True
    test_user.totp_secret = encrypt_secret("JBSWY3DPEHPK3PXP")
    await db.commit()

    resp = await authed_client.post(
        "/api/v1/auth/totp/disable", json={"password": "wrongpassword"},
    )
    assert resp.status_code == 400


async def test_totp_disable_not_enabled(authed_client, test_user):
    resp = await authed_client.post(
        "/api/v1/auth/totp/disable", json={"password": "password1234"},
    )
    assert resp.status_code == 400


async def test_login_with_totp_enabled(app_client, test_user, db, mock_valkey):
    from app.services.totp_service import encrypt_secret

    test_user.totp_enabled = True
    test_user.totp_secret = encrypt_secret("JBSWY3DPEHPK3PXP")
    await db.commit()

    # Reset mock to not return any session (simulating unauthenticated)
    mock_valkey.get = AsyncMock(return_value=None)

    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"username": "testuser", "password": "password1234"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["requires_totp"] is True
    assert "totp_token" in data
    mock_valkey.set.assert_called()


# ── TOTP verify tests (with brute-force protection) ──


def _totp_verify_get_side_effect(user_id_str):
    """Return a side_effect for mock_valkey.get that handles TOTP verify flow.

    First call (totp_attempts:*) returns None (no lockout).
    Second call (totp_pending:*) returns user_id_str.
    """
    async def side_effect(key):
        if key.startswith("totp_attempts:"):
            return None
        if key.startswith("totp_pending:"):
            return user_id_str
        return None
    return side_effect


async def test_totp_verify_success(app_client, test_user, db, mock_valkey):
    from app.services.totp_service import encrypt_secret

    secret = "JBSWY3DPEHPK3PXP"
    test_user.totp_enabled = True
    test_user.totp_secret = encrypt_secret(secret)
    await db.commit()

    totp_token = uuid.uuid4().hex
    mock_valkey.get = AsyncMock(
        side_effect=_totp_verify_get_side_effect(str(test_user.id)),
    )

    totp = pyotp.TOTP(secret)
    code = totp.now()

    resp = await app_client.post(
        "/api/v1/auth/totp/verify",
        json={"totp_token": totp_token, "code": code},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    # Attempt counter should be deleted on success
    mock_valkey.delete.assert_any_call(f"totp_attempts:{totp_token}")


async def test_totp_verify_invalid_code(app_client, test_user, db, mock_valkey):
    from app.services.totp_service import encrypt_secret

    test_user.totp_enabled = True
    test_user.totp_secret = encrypt_secret("JBSWY3DPEHPK3PXP")
    await db.commit()

    totp_token = uuid.uuid4().hex
    mock_valkey.get = AsyncMock(
        side_effect=_totp_verify_get_side_effect(str(test_user.id)),
    )

    resp = await app_client.post(
        "/api/v1/auth/totp/verify",
        json={"totp_token": totp_token, "code": "000000"},
    )
    assert resp.status_code == 401
    # Attempt counter should be incremented on failure
    mock_valkey.incr.assert_called_with(f"totp_attempts:{totp_token}")
    mock_valkey.expire.assert_called_with(f"totp_attempts:{totp_token}", 300)


async def test_totp_verify_expired_token(app_client, mock_valkey):
    mock_valkey.get = AsyncMock(return_value=None)

    resp = await app_client.post(
        "/api/v1/auth/totp/verify",
        json={"totp_token": "expired-token", "code": "123456"},
    )
    assert resp.status_code == 401


async def test_totp_verify_with_recovery_code(
    app_client, test_user, db, mock_valkey,
):
    import bcrypt as _bcrypt

    from app.services.totp_service import encrypt_secret

    secret = "JBSWY3DPEHPK3PXP"
    test_user.totp_enabled = True
    test_user.totp_secret = encrypt_secret(secret)
    recovery_code = "abc12-xyz34"
    hashed = _bcrypt.hashpw(
        recovery_code.encode(), _bcrypt.gensalt(),
    ).decode()
    test_user.totp_recovery_codes = [hashed]
    await db.commit()

    totp_token = uuid.uuid4().hex
    mock_valkey.get = AsyncMock(
        side_effect=_totp_verify_get_side_effect(str(test_user.id)),
    )

    resp = await app_client.post(
        "/api/v1/auth/totp/verify",
        json={"totp_token": totp_token, "code": recovery_code},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ── Brute-force protection tests ──


async def test_totp_verify_lockout_after_max_attempts(
    app_client, test_user, db, mock_valkey,
):
    """After 5 failed attempts, return 429 Too Many Requests."""
    from app.services.totp_service import encrypt_secret

    test_user.totp_enabled = True
    test_user.totp_secret = encrypt_secret("JBSWY3DPEHPK3PXP")
    await db.commit()

    totp_token = uuid.uuid4().hex

    # Simulate that 5 attempts have already been made
    async def side_effect(key):
        if key.startswith("totp_attempts:"):
            return "5"
        if key.startswith("totp_pending:"):
            return str(test_user.id)
        return None

    mock_valkey.get = AsyncMock(side_effect=side_effect)

    resp = await app_client.post(
        "/api/v1/auth/totp/verify",
        json={"totp_token": totp_token, "code": "000000"},
    )
    assert resp.status_code == 429
    assert "Too many TOTP attempts" in resp.json()["detail"]


async def test_totp_verify_lockout_blocks_valid_code(
    app_client, test_user, db, mock_valkey,
):
    """Even a valid code should be rejected when locked out."""
    from app.services.totp_service import encrypt_secret

    secret = "JBSWY3DPEHPK3PXP"
    test_user.totp_enabled = True
    test_user.totp_secret = encrypt_secret(secret)
    await db.commit()

    totp_token = uuid.uuid4().hex
    totp = pyotp.TOTP(secret)
    code = totp.now()

    # Simulate lockout (>= 5 attempts)
    async def side_effect(key):
        if key.startswith("totp_attempts:"):
            return "7"
        if key.startswith("totp_pending:"):
            return str(test_user.id)
        return None

    mock_valkey.get = AsyncMock(side_effect=side_effect)

    resp = await app_client.post(
        "/api/v1/auth/totp/verify",
        json={"totp_token": totp_token, "code": code},
    )
    assert resp.status_code == 429


async def test_totp_verify_attempts_below_limit_allowed(
    app_client, test_user, db, mock_valkey,
):
    """With fewer than 5 attempts, verification should proceed normally."""
    from app.services.totp_service import encrypt_secret

    secret = "JBSWY3DPEHPK3PXP"
    test_user.totp_enabled = True
    test_user.totp_secret = encrypt_secret(secret)
    await db.commit()

    totp_token = uuid.uuid4().hex
    totp = pyotp.TOTP(secret)
    code = totp.now()

    # Simulate 4 previous attempts (just under the limit)
    async def side_effect(key):
        if key.startswith("totp_attempts:"):
            return "4"
        if key.startswith("totp_pending:"):
            return str(test_user.id)
        return None

    mock_valkey.get = AsyncMock(side_effect=side_effect)

    resp = await app_client.post(
        "/api/v1/auth/totp/verify",
        json={"totp_token": totp_token, "code": code},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


async def test_totp_verify_failed_recovery_code_increments_counter(
    app_client, test_user, db, mock_valkey,
):
    """A failed recovery code attempt should increment the counter."""
    from app.services.totp_service import encrypt_secret, hash_recovery_codes

    secret = "JBSWY3DPEHPK3PXP"
    test_user.totp_enabled = True
    test_user.totp_secret = encrypt_secret(secret)
    test_user.totp_recovery_codes = hash_recovery_codes(["abc12-xyz34"])
    await db.commit()

    totp_token = uuid.uuid4().hex
    mock_valkey.get = AsyncMock(
        side_effect=_totp_verify_get_side_effect(str(test_user.id)),
    )

    resp = await app_client.post(
        "/api/v1/auth/totp/verify",
        json={"totp_token": totp_token, "code": "wrong-code0"},
    )
    assert resp.status_code == 401
    mock_valkey.incr.assert_called_with(f"totp_attempts:{totp_token}")
    mock_valkey.expire.assert_called_with(f"totp_attempts:{totp_token}", 300)


async def test_totp_status_enabled(authed_client, test_user, db):
    test_user.totp_enabled = True
    await db.commit()

    resp = await authed_client.get("/api/v1/auth/totp/status")
    assert resp.status_code == 200
    assert resp.json()["totp_enabled"] is True


async def test_totp_status_disabled(authed_client, test_user):
    resp = await authed_client.get("/api/v1/auth/totp/status")
    assert resp.status_code == 200
    assert resp.json()["totp_enabled"] is False


async def test_login_without_totp(app_client, test_user, mock_valkey):
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"username": "testuser", "password": "password1234"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert "requires_totp" not in resp.json()
