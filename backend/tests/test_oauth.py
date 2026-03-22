"""Tests for OAuth 2.0 endpoints."""

import re

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
    assert data["redirect_uris"] == ["http://localhost:3000/callback"]
    assert data["scopes"] == ["read", "write"]
    assert data["client_secret_expires_at"] == 0
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


async def test_authorize_logged_in_shows_consent(app_client, db, mock_valkey, test_user):
    """H-1: Logged-in user sees consent form instead of auto-redirect."""
    app_data = await _create_test_app(app_client, mock_valkey)
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
    assert resp.status_code == 200
    assert "Authorize" in resp.text


async def test_authorize_expired_session(app_client, db, mock_valkey):
    """Expired session shows login form."""
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
    assert resp.status_code == 200
    assert "log in" in resp.text.lower()


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


async def _authorize_via_consent(client, mock_valkey, *, client_id, redirect_uri,
                                 scope="read write"):
    """Get consent form, extract CSRF token, POST to authorize."""
    consent_resp = await client.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": scope,
        },
        follow_redirects=False,
    )
    assert consent_resp.status_code == 200
    csrf_match = re.search(r'name="csrf_token"\s+value="([^"]+)"', consent_resp.text)
    assert csrf_match
    csrf_token = csrf_match.group(1)

    original_get = mock_valkey.get
    async def _csrf_aware_get(key):
        if key.startswith("csrf:"):
            return "1"
        return await original_get(key)
    mock_valkey.get = _csrf_aware_get

    auth_resp = await client.post(
        "/oauth/authorize",
        data={
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "response_type": "code",
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )
    mock_valkey.get = original_get
    assert auth_resp.status_code == 302
    location = auth_resp.headers["location"]
    return location.split("code=")[1].split("&")[0]


async def test_token_authorization_code_flow(app_client, db, mock_valkey, test_user):
    """Full authorization code flow: create app, consent, exchange token."""
    app_data = await _create_test_app(app_client, mock_valkey)

    # Step 1: Authorize via consent form
    mock_valkey.get = AsyncMock(return_value=str(test_user.id))
    app_client.cookies.set("nekonoverse_session", "test-oauth-session")

    code = await _authorize_via_consent(
        app_client, mock_valkey,
        client_id=app_data["client_id"],
        redirect_uri="http://localhost:3000/callback",
    )

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


# ── GET /oauth/passkey.js ─────────────────────────────────────────────


async def test_oauth_passkey_js_endpoint(app_client):
    """passkey.js is served as external JavaScript (CSP compatible)."""
    resp = await app_client.get("/oauth/passkey.js")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/javascript")
    assert "Cache-Control" in resp.headers
    assert "passkeyLogin" in resp.text
    assert "DOMContentLoaded" in resp.text


async def test_login_form_uses_external_passkey_js(app_client, db, mock_valkey):
    """Login form references external passkey.js instead of inline script."""
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
    # External script tag is present
    assert 'src="/oauth/passkey.js"' in resp.text
    # No inline script or onclick handler
    assert "onclick=" not in resp.text
    assert "function passkeyLogin" not in resp.text


# ── OOB (Out-of-Band) flow ───────────────────────────────────────────


async def _create_oob_app(app_client, mock_valkey):
    """Create an OAuth app with OOB redirect_uri."""
    resp = await app_client.post(
        "/api/v1/apps",
        json={
            "client_name": "OOBTestApp",
            "redirect_uris": "urn:ietf:wg:oauth:2.0:oob",
            "scopes": "read write",
        },
    )
    assert resp.status_code == 200
    return resp.json()


async def test_oob_authorize_shows_code_page(app_client, db, mock_valkey, test_user):
    """OOB flow: after login, display authorization code on page instead of redirect."""
    app_data = await _create_oob_app(app_client, mock_valkey)

    mock_valkey.get = AsyncMock(return_value=str(test_user.id))
    app_client.cookies.set("nekonoverse_session", "test-oob-session")

    # Get consent form
    consent_resp = await app_client.get(
        "/oauth/authorize",
        params={
            "client_id": app_data["client_id"],
            "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
            "response_type": "code",
            "scope": "read write",
        },
        follow_redirects=False,
    )
    assert consent_resp.status_code == 200
    csrf_match = re.search(r'name="csrf_token"\s+value="([^"]+)"', consent_resp.text)
    assert csrf_match
    csrf_token = csrf_match.group(1)

    original_get = mock_valkey.get
    async def _csrf_aware_get(key):
        if key.startswith("csrf:"):
            return "1"
        return await original_get(key)
    mock_valkey.get = _csrf_aware_get

    # Submit consent — should return HTML page with code, NOT a redirect
    auth_resp = await app_client.post(
        "/oauth/authorize",
        data={
            "client_id": app_data["client_id"],
            "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
            "scope": "read write",
            "response_type": "code",
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )
    mock_valkey.get = original_get

    assert auth_resp.status_code == 200
    assert "Authorization successful" in auth_resp.text
    assert "Authorization Code" in auth_resp.text

    # Extract the code from the page
    code_match = re.search(r'class="code">([^<]+)<', auth_resp.text)
    assert code_match
    code = code_match.group(1)
    assert len(code) > 10  # sanity check

    return app_data, code


async def test_oob_token_exchange(app_client, db, mock_valkey, test_user):
    """OOB flow: code displayed on page can be exchanged for a token."""
    app_data, code = await test_oob_authorize_shows_code_page(
        app_client, db, mock_valkey, test_user
    )

    resp = await app_client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": app_data["client_id"],
            "client_secret": app_data["client_secret"],
            "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"]
    assert data["token_type"] == "Bearer"
