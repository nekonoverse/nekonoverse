import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

PASSKEY_SVC = "app.services.passkey_service"


# ── Registration options ──────────────────────────────────────────────────


async def test_register_options_requires_auth(app_client, mock_valkey):
    resp = await app_client.post("/api/v1/passkey/register/options")
    assert resp.status_code == 401


async def test_register_options_success(authed_client, test_user, mock_valkey):
    mock_gen = AsyncMock(return_value={
        "rp": {"name": "Nekonoverse", "id": "localhost"},
        "challenge": "AAAA",
        "user": {
            "id": str(test_user.id),
            "name": "testuser",
            "displayName": "Test User",
        },
        "pubKeyCredParams": [],
    })
    with patch(f"{PASSKEY_SVC}.generate_registration_options", mock_gen):
        resp = await authed_client.post(
            "/api/v1/passkey/register/options",
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "challenge" in data
    assert data["rp"]["name"] == "Nekonoverse"


# ── Registration verify ───────────────────────────────────────────────────


async def test_register_verify_requires_auth(app_client, mock_valkey):
    resp = await app_client.post("/api/v1/passkey/register/verify", json={
        "id": "abc", "rawId": "abc", "type": "public-key",
        "response": {}, "name": "My Key",
    })
    assert resp.status_code == 401


async def test_register_verify_success(authed_client, test_user, mock_valkey):
    fake_passkey = MagicMock()
    fake_passkey.id = uuid.uuid4()
    fake_passkey.credential_id = b"\x01\x02\x03"
    fake_passkey.name = "My Key"
    fake_passkey.aaguid = "00000000-0000-0000-0000-000000000000"
    fake_passkey.sign_count = 0
    fake_passkey.created_at = datetime.now(timezone.utc)
    fake_passkey.last_used_at = None

    mock_verify = AsyncMock(return_value=fake_passkey)
    with patch(f"{PASSKEY_SVC}.verify_registration_response", mock_verify):
        resp = await authed_client.post(
            "/api/v1/passkey/register/verify",
            json={
                "id": "abc", "rawId": "abc", "type": "public-key",
                "response": {
                    "attestationObject": "AA",
                    "clientDataJSON": "BB",
                },
                "name": "My Key",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "My Key"
    assert data["sign_count"] == 0


async def test_register_verify_invalid_challenge(
    authed_client, test_user, mock_valkey,
):
    mock_verify = AsyncMock(
        side_effect=ValueError("Challenge expired or not found"),
    )
    with patch(f"{PASSKEY_SVC}.verify_registration_response", mock_verify):
        resp = await authed_client.post(
            "/api/v1/passkey/register/verify",
            json={
                "id": "abc", "rawId": "abc", "type": "public-key",
                "response": {
                    "attestationObject": "AA",
                    "clientDataJSON": "BB",
                },
            },
        )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Passkey registration failed"


# ── Authentication options ────────────────────────────────────────────────


async def test_authenticate_options(app_client, mock_valkey):
    mock_gen = AsyncMock(return_value={
        "challenge": "BBBB",
        "rpId": "localhost",
        "allowCredentials": [],
        "userVerification": "preferred",
    })
    with patch(f"{PASSKEY_SVC}.generate_authentication_options", mock_gen):
        resp = await app_client.post(
            "/api/v1/passkey/authenticate/options",
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "challengeId" in data
    assert "challenge" in data


# ── Authentication verify ─────────────────────────────────────────────────


async def test_authenticate_verify_success(
    app_client, test_user, mock_valkey,
):
    mock_verify = AsyncMock(return_value=test_user)
    with patch(
        f"{PASSKEY_SVC}.verify_authentication_response", mock_verify,
    ):
        resp = await app_client.post(
            "/api/v1/passkey/authenticate/verify",
            json={
                "challengeId": "test-challenge-id",
                "id": "abc", "rawId": "abc", "type": "public-key",
                "response": {
                    "authenticatorData": "AA",
                    "clientDataJSON": "BB",
                    "signature": "CC",
                },
            },
        )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert "nekonoverse_session" in resp.cookies
    mock_valkey.set.assert_called()


async def test_authenticate_verify_totp_user_gets_session(
    app_client, db, test_user, mock_valkey,
):
    """Passkey is MFA by itself — TOTP user still gets session directly."""
    totp_user = MagicMock()
    totp_user.id = test_user.id
    totp_user.totp_enabled = True

    mock_verify = AsyncMock(return_value=totp_user)
    with patch(
        f"{PASSKEY_SVC}.verify_authentication_response", mock_verify,
    ):
        resp = await app_client.post(
            "/api/v1/passkey/authenticate/verify",
            json={
                "challengeId": "test-challenge-id",
                "id": "abc", "rawId": "abc", "type": "public-key",
                "response": {
                    "authenticatorData": "AA",
                    "clientDataJSON": "BB",
                    "signature": "CC",
                },
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "nekonoverse_session" in resp.cookies
    # Should NOT require TOTP — Passkey is already MFA
    assert "requires_totp" not in data


async def test_authenticate_verify_invalid(app_client, mock_valkey):
    mock_verify = AsyncMock(
        side_effect=ValueError("Challenge expired or not found"),
    )
    with patch(
        f"{PASSKEY_SVC}.verify_authentication_response", mock_verify,
    ):
        resp = await app_client.post(
            "/api/v1/passkey/authenticate/verify",
            json={
                "challengeId": "bad-challenge",
                "id": "abc", "rawId": "abc", "type": "public-key",
                "response": {
                    "authenticatorData": "AA",
                    "clientDataJSON": "BB",
                    "signature": "CC",
                },
            },
        )
    assert resp.status_code == 401


# ── Credential listing ────────────────────────────────────────────────────


async def test_list_credentials_requires_auth(app_client, mock_valkey):
    resp = await app_client.get("/api/v1/passkey/credentials")
    assert resp.status_code == 401


async def test_list_credentials_empty(
    authed_client, test_user, mock_valkey,
):
    mock_list = AsyncMock(return_value=[])
    with patch(f"{PASSKEY_SVC}.list_passkeys", mock_list):
        resp = await authed_client.get("/api/v1/passkey/credentials")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_credentials_with_data(
    authed_client, test_user, mock_valkey,
):
    fake_pk = MagicMock()
    fake_pk.id = uuid.uuid4()
    fake_pk.credential_id = b"\x01\x02\x03"
    fake_pk.name = "Laptop"
    fake_pk.aaguid = "00000000-0000-0000-0000-000000000000"
    fake_pk.sign_count = 5
    fake_pk.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    fake_pk.last_used_at = datetime(2025, 6, 15, tzinfo=timezone.utc)

    mock_list = AsyncMock(return_value=[fake_pk])
    with patch(f"{PASSKEY_SVC}.list_passkeys", mock_list):
        resp = await authed_client.get("/api/v1/passkey/credentials")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "Laptop"
    assert data[0]["sign_count"] == 5
    assert data[0]["last_used_at"] is not None


# ── Credential deletion ──────────────────────────────────────────────────


async def test_delete_credential_requires_auth(app_client, mock_valkey):
    pk_id = uuid.uuid4()
    resp = await app_client.delete(
        f"/api/v1/passkey/credentials/{pk_id}",
    )
    assert resp.status_code == 401


async def test_delete_credential_success(
    authed_client, test_user, mock_valkey,
):
    pk_id = uuid.uuid4()
    mock_del = AsyncMock(return_value=None)
    with patch(f"{PASSKEY_SVC}.delete_passkey", mock_del):
        resp = await authed_client.delete(
            f"/api/v1/passkey/credentials/{pk_id}",
        )
    assert resp.status_code == 204


async def test_delete_credential_not_found(
    authed_client, test_user, mock_valkey,
):
    pk_id = uuid.uuid4()
    mock_del = AsyncMock(side_effect=ValueError("Passkey not found"))
    with patch(f"{PASSKEY_SVC}.delete_passkey", mock_del):
        resp = await authed_client.delete(
            f"/api/v1/passkey/credentials/{pk_id}",
        )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]
