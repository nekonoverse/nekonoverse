"""Tests for OAuth 2.0 endpoints."""

from unittest.mock import AsyncMock

# ── POST /api/v1/apps ───────────────────────────────────────────────────


async def test_create_app(app_client, db, mock_valkey):
    """Register an OAuth application."""
    resp = await app_client.post(
        "/api/v1/apps",
        json={
            "client_name": "TestApp",
            "redirect_uris": "http://localhost:3000/callback",
            "scopes": "read write",
            "website": "https://example.com",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "TestApp"
    assert data["client_id"]
    assert data["client_secret"]
    assert data["redirect_uri"] == "http://localhost:3000/callback"
    assert data["website"] == "https://example.com"
    return data


async def test_create_app_minimal(app_client, db, mock_valkey):
    resp = await app_client.post(
        "/api/v1/apps",
        json={
            "client_name": "MinApp",
            "redirect_uris": "urn:ietf:wg:oauth:2.0:oob",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "MinApp"


# ── GET /oauth/authorize ────────────────────────────────────────────────


async def _create_test_app(app_client, mock_valkey):
    resp = await app_client.post(
        "/api/v1/apps",
        json={
            "client_name": "AuthTestApp",
            "redirect_uris": "http://localhost:3000/callback",
            "scopes": "read write",
        },
    )
    return resp.json()


async def test_authorize_invalid_client_id(app_client, db, mock_valkey):
    resp = await app_client.get(
        "/oauth/authorize",
        params={
            "client_id": "nonexistent",
            "redirect_uri": "http://localhost/callback",
            "response_type": "code",
        },
    )
    assert resp.status_code == 400


async def test_authorize_not_logged_in(app_client, db, mock_valkey):
    """Without a session cookie, show login form."""
    app_data = await _create_test_app(app_client, mock_valkey)
    resp = await app_client.get(
        "/oauth/authorize",
        params={
            "client_id": app_data["client_id"],
            "redirect_uri": "http://localhost:3000/callback",
            "response_type": "code",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "log in" in resp.text.lower()


async def test_authorize_invalid_redirect_uri(app_client, db, mock_valkey):
    app_data = await _create_test_app(app_client, mock_valkey)
    resp = await app_client.get(
        "/oauth/authorize",
        params={
            "client_id": app_data["client_id"],
            "redirect_uri": "http://evil.example/callback",
            "response_type": "code",
        },
    )
    assert resp.status_code == 400


async def test_authorize_logged_in_redirects(app_client, db, mock_valkey, test_user):
    """Logged-in user gets redirected with an auth code."""
    app_data = await _create_test_app(app_client, mock_valkey)
    # セッションクッキーを設定
    mock_valkey.get = AsyncMock(return_value=str(test_user.id))
    app_client.cookies.set("nekonoverse_session", "test-session")

    resp = await app_client.get(
        "/oauth/authorize",
        params={
            "client_id": app_data["client_id"],
            "redirect_uri": "http://localhost:3000/callback",
            "response_type": "code",
            "state": "test-state",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert "code=" in location
    assert "state=test-state" in location


async def test_authorize_expired_session(app_client, db, mock_valkey):
    """Expired session returns 401."""
    app_data = await _create_test_app(app_client, mock_valkey)
    mock_valkey.get = AsyncMock(return_value=None)
    app_client.cookies.set("nekonoverse_session", "expired-session")

    resp = await app_client.get(
        "/oauth/authorize",
        params={
            "client_id": app_data["client_id"],
            "redirect_uri": "http://localhost:3000/callback",
            "response_type": "code",
        },
    )
    assert resp.status_code == 401


# ── POST /oauth/token ───────────────────────────────────────────────────


async def test_token_invalid_client(app_client, db, mock_valkey):
    resp = await app_client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "nonexistent",
            "client_secret": "wrong",
            "code": "anything",
        },
    )
    assert resp.status_code == 401


async def test_token_client_credentials(app_client, db, mock_valkey):
    """client_credentials grant returns a token."""
    app_data = await _create_test_app(app_client, mock_valkey)
    resp = await app_client.post(
        "/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": app_data["client_id"],
            "client_secret": app_data["client_secret"],
            "scope": "read",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"]
    assert data["token_type"] == "Bearer"
    assert data["scope"] == "read"


async def test_token_unsupported_grant_type(app_client, db, mock_valkey):
    app_data = await _create_test_app(app_client, mock_valkey)
    resp = await app_client.post(
        "/oauth/token",
        data={
            "grant_type": "unsupported",
            "client_id": app_data["client_id"],
            "client_secret": app_data["client_secret"],
        },
    )
    assert resp.status_code == 400


async def test_token_authorization_code_flow(app_client, db, mock_valkey, test_user):
    """Full authorization code flow: create app, authorize, exchange token."""
    app_data = await _create_test_app(app_client, mock_valkey)

    # Step 1: Authorize
    mock_valkey.get = AsyncMock(return_value=str(test_user.id))
    app_client.cookies.set("nekonoverse_session", "test-oauth-session")

    resp = await app_client.get(
        "/oauth/authorize",
        params={
            "client_id": app_data["client_id"],
            "redirect_uri": "http://localhost:3000/callback",
            "response_type": "code",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    location = resp.headers["location"]
    code = location.split("code=")[1].split("&")[0]

    # Step 2: Exchange code for token
    resp = await app_client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": app_data["client_id"],
            "client_secret": app_data["client_secret"],
            "redirect_uri": "http://localhost:3000/callback",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"]
    assert data["token_type"] == "Bearer"


async def test_token_invalid_code(app_client, db, mock_valkey):
    app_data = await _create_test_app(app_client, mock_valkey)
    resp = await app_client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": "invalid-code",
            "client_id": app_data["client_id"],
            "client_secret": app_data["client_secret"],
        },
    )
    assert resp.status_code == 400


async def test_token_missing_code(app_client, db, mock_valkey):
    app_data = await _create_test_app(app_client, mock_valkey)
    resp = await app_client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": app_data["client_id"],
            "client_secret": app_data["client_secret"],
        },
    )
    assert resp.status_code == 400


# ── POST /oauth/revoke ──────────────────────────────────────────────────


async def test_revoke_token(app_client, db, mock_valkey, test_user):
    """Revoke an existing token."""
    app_data = await _create_test_app(app_client, mock_valkey)
    # client_credentials トークンを作成
    resp = await app_client.post(
        "/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": app_data["client_id"],
            "client_secret": app_data["client_secret"],
        },
    )
    access_token = resp.json()["access_token"]

    # トークンを取り消し
    resp = await app_client.post(
        "/oauth/revoke",
        data={
            "token": access_token,
            "client_id": app_data["client_id"],
            "client_secret": app_data["client_secret"],
        },
    )
    assert resp.status_code == 200


async def test_revoke_nonexistent_token(app_client, db, mock_valkey):
    """Revoking with invalid client credentials returns 401."""
    resp = await app_client.post(
        "/oauth/revoke",
        data={
            "token": "nonexistent-token",
            "client_id": "x",
            "client_secret": "y",
        },
    )
    assert resp.status_code == 401


async def test_revoke_nonexistent_token_valid_client(app_client, db, mock_valkey):
    """Revoking a nonexistent token with valid client returns 200 (idempotent)."""
    app_data = await _create_test_app(app_client, mock_valkey)
    resp = await app_client.post(
        "/oauth/revoke",
        data={
            "token": "nonexistent-token",
            "client_id": app_data["client_id"],
            "client_secret": app_data["client_secret"],
        },
    )
    assert resp.status_code == 200
