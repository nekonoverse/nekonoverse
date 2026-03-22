"""Tests for OAuth TOTP bypass fix (H-2) and Passkey authentication."""

import json

from unittest.mock import AsyncMock, patch


async def _create_test_app(app_client, mock_valkey):
    resp = await app_client.post(
        "/api/v1/apps",
        json={
            "client_name": "TOTPTestApp",
            "redirect_uris": "http://localhost:3000/callback",
            "scopes": "read write",
        },
    )
    return resp.json()


# ── Password login + TOTP ──────────────────────────────────────────────


async def test_oauth_login_totp_required(
    app_client, db, test_user, mock_valkey,
):
    """H-2: Password auth with TOTP enabled must show TOTP form, not issue code."""
    app_data = await _create_test_app(app_client, mock_valkey)

    test_user.totp_enabled = True
    test_user.totp_secret = "encrypted_test_secret"
    await db.flush()

    resp = await app_client.post(
        "/oauth/authorize",
        data={
            "client_id": app_data["client_id"],
            "redirect_uri": "http://localhost:3000/callback",
            "scope": "read write",
            "response_type": "code",
            "username": "testuser",
            "password": "password1234",
        },
        follow_redirects=False,
    )

    # Must NOT redirect — no auth code should be issued
    assert resp.status_code == 200
    assert "Two-Factor Authentication" in resp.text
    assert "totp_token" in resp.text
    assert "totp_code" in resp.text
    # Verify Valkey stored the pending TOTP data
    set_calls = [str(c) for c in mock_valkey.set.call_args_list]
    assert any("totp_pending_oauth:" in c for c in set_calls)


async def test_oauth_login_totp_verify_success(
    app_client, db, test_user, mock_valkey,
):
    """TOTP verification after password auth issues authorization code."""
    app_data = await _create_test_app(app_client, mock_valkey)

    test_user.totp_enabled = True
    test_user.totp_secret = "encrypted_test_secret"
    await db.flush()

    totp_data = json.dumps({
        "user_id": str(test_user.id),
        "client_id": app_data["client_id"],
        "redirect_uri": "http://localhost:3000/callback",
        "scope": "read write",
        "response_type": "code",
        "state": "test-state",
        "code_challenge": None,
        "code_challenge_method": None,
        "app_name": "TOTPTestApp",
    })

    original_get = mock_valkey.get

    async def _totp_aware_get(key):
        if key.startswith("totp_pending_oauth:"):
            return totp_data
        return await original_get(key)

    mock_valkey.get = _totp_aware_get

    with patch(
        "app.services.totp_service.decrypt_secret", return_value="plain_secret",
    ), patch(
        "app.services.totp_service.verify_totp_code", return_value=True,
    ):
        resp = await app_client.post(
            "/oauth/authorize",
            data={
                "totp_token": "test-totp-token",
                "totp_code": "123456",
            },
            follow_redirects=False,
        )

    mock_valkey.get = original_get

    assert resp.status_code == 302
    location = resp.headers["location"]
    assert "code=" in location
    assert "state=test-state" in location
    assert location.startswith("http://localhost:3000/callback")


async def test_oauth_login_totp_verify_invalid(
    app_client, db, test_user, mock_valkey,
):
    """Invalid TOTP code shows error on TOTP form."""
    app_data = await _create_test_app(app_client, mock_valkey)

    test_user.totp_enabled = True
    test_user.totp_secret = "encrypted_test_secret"
    test_user.totp_recovery_codes = None
    await db.flush()

    totp_data = json.dumps({
        "user_id": str(test_user.id),
        "client_id": app_data["client_id"],
        "redirect_uri": "http://localhost:3000/callback",
        "scope": "read write",
        "response_type": "code",
        "state": None,
        "code_challenge": None,
        "code_challenge_method": None,
        "app_name": "TOTPTestApp",
    })

    original_get = mock_valkey.get

    async def _totp_aware_get(key):
        if key.startswith("totp_pending_oauth:"):
            return totp_data
        return await original_get(key)

    mock_valkey.get = _totp_aware_get

    with patch(
        "app.services.totp_service.decrypt_secret", return_value="plain_secret",
    ), patch(
        "app.services.totp_service.verify_totp_code", return_value=False,
    ):
        resp = await app_client.post(
            "/oauth/authorize",
            data={
                "totp_token": "test-totp-token",
                "totp_code": "000000",
            },
            follow_redirects=False,
        )

    mock_valkey.get = original_get

    assert resp.status_code == 200
    assert "Invalid verification code" in resp.text
    assert "totp_token" in resp.text


# ── Passkey login via OAuth ────────────────────────────────────────────


async def test_oauth_passkey_login(
    app_client, db, test_user, mock_valkey,
):
    """Passkey authentication in OAuth flow issues authorization code."""
    app_data = await _create_test_app(app_client, mock_valkey)

    passkey_payload = json.dumps({
        "challengeId": "test-challenge-id",
        "id": "cred-id",
        "rawId": "cred-raw-id",
        "type": "public-key",
        "response": {
            "authenticatorData": "AA",
            "clientDataJSON": "BB",
            "signature": "CC",
        },
    })

    mock_verify = AsyncMock(return_value=test_user)
    with patch(
        "app.services.passkey_service.verify_authentication_response",
        mock_verify,
    ):
        resp = await app_client.post(
            "/oauth/authorize",
            data={
                "client_id": app_data["client_id"],
                "redirect_uri": "http://localhost:3000/callback",
                "scope": "read write",
                "response_type": "code",
                "passkey_credential": passkey_payload,
            },
            follow_redirects=False,
        )

    assert resp.status_code == 302
    location = resp.headers["location"]
    assert "code=" in location
    assert location.startswith("http://localhost:3000/callback")


async def test_oauth_passkey_with_totp_skips_totp(
    app_client, db, test_user, mock_valkey,
):
    """Passkey is MFA by itself — TOTP enabled user still gets auth code directly."""
    app_data = await _create_test_app(app_client, mock_valkey)

    test_user.totp_enabled = True
    test_user.totp_secret = "encrypted_test_secret"
    await db.flush()

    passkey_payload = json.dumps({
        "challengeId": "test-challenge-id",
        "id": "cred-id",
        "rawId": "cred-raw-id",
        "type": "public-key",
        "response": {
            "authenticatorData": "AA",
            "clientDataJSON": "BB",
            "signature": "CC",
        },
    })

    mock_verify = AsyncMock(return_value=test_user)
    with patch(
        "app.services.passkey_service.verify_authentication_response",
        mock_verify,
    ):
        resp = await app_client.post(
            "/oauth/authorize",
            data={
                "client_id": app_data["client_id"],
                "redirect_uri": "http://localhost:3000/callback",
                "scope": "read write",
                "response_type": "code",
                "passkey_credential": passkey_payload,
            },
            follow_redirects=False,
        )

    # Passkey is already MFA — should issue auth code without TOTP
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert "code=" in location
    assert location.startswith("http://localhost:3000/callback")


# ── OOB + Passkey / TOTP ─────────────────────────────────────────────


async def _create_oob_app(app_client, mock_valkey):
    resp = await app_client.post(
        "/api/v1/apps",
        json={
            "client_name": "OOBTestApp",
            "redirect_uris": "urn:ietf:wg:oauth:2.0:oob",
            "scopes": "read write",
        },
    )
    return resp.json()


async def test_oauth_passkey_oob(app_client, db, test_user, mock_valkey):
    """Passkey + OOB: should display auth code on page, not redirect."""
    app_data = await _create_oob_app(app_client, mock_valkey)

    passkey_payload = json.dumps({
        "challengeId": "test-challenge-id",
        "id": "cred-id",
        "rawId": "cred-raw-id",
        "type": "public-key",
        "response": {
            "authenticatorData": "AA",
            "clientDataJSON": "BB",
            "signature": "CC",
        },
    })

    mock_verify = AsyncMock(return_value=test_user)
    with patch(
        "app.services.passkey_service.verify_authentication_response",
        mock_verify,
    ):
        resp = await app_client.post(
            "/oauth/authorize",
            data={
                "client_id": app_data["client_id"],
                "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
                "scope": "read write",
                "response_type": "code",
                "passkey_credential": passkey_payload,
            },
            follow_redirects=False,
        )

    assert resp.status_code == 200
    assert "Authorization successful" in resp.text
    assert "Authorization Code" in resp.text


async def test_oauth_totp_oob(app_client, db, test_user, mock_valkey):
    """TOTP + OOB: after TOTP verification, display auth code on page."""
    app_data = await _create_oob_app(app_client, mock_valkey)

    test_user.totp_enabled = True
    test_user.totp_secret = "encrypted_test_secret"
    await db.flush()

    totp_data = json.dumps({
        "user_id": str(test_user.id),
        "client_id": app_data["client_id"],
        "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
        "scope": "read write",
        "response_type": "code",
        "state": None,
        "code_challenge": None,
        "code_challenge_method": None,
        "app_name": "OOBTestApp",
    })

    original_get = mock_valkey.get

    async def _totp_aware_get(key):
        if key.startswith("totp_pending_oauth:"):
            return totp_data
        return await original_get(key)

    mock_valkey.get = _totp_aware_get

    with patch(
        "app.services.totp_service.decrypt_secret", return_value="plain_secret",
    ), patch(
        "app.services.totp_service.verify_totp_code", return_value=True,
    ):
        resp = await app_client.post(
            "/oauth/authorize",
            data={
                "totp_token": "test-totp-token",
                "totp_code": "123456",
            },
            follow_redirects=False,
        )

    mock_valkey.get = original_get

    assert resp.status_code == 200
    assert "Authorization successful" in resp.text
    assert "Authorization Code" in resp.text
