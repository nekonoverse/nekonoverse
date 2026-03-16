import hashlib
import base64
import re
import secrets
from urllib.parse import parse_qs, urlparse


async def _authorize_via_consent(client, mock_valkey, *, client_id, redirect_uri, scope="read",
                                 code_challenge=None, code_challenge_method=None):
    """GET /oauth/authorize で同意画面を取得し、CSRFトークンを含めてPOSTで認可する。"""
    params = {
        "response_type": "code", "client_id": client_id,
        "redirect_uri": redirect_uri, "scope": scope,
    }
    if code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = code_challenge_method

    consent_resp = await client.get("/oauth/authorize", params=params, follow_redirects=False)
    assert consent_resp.status_code == 200

    # HTMLからCSRFトークンを抽出
    html = consent_resp.text
    csrf_match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert csrf_match, "CSRF token not found in consent form"
    csrf_token = csrf_match.group(1)

    # mock_valkeyがCSRFトークンを検証できるようにする
    original_get = mock_valkey.get
    async def _csrf_aware_get(key):
        if key.startswith("csrf:"):
            return "1"
        return await original_get(key)
    mock_valkey.get = _csrf_aware_get

    form_data = {
        "client_id": client_id, "redirect_uri": redirect_uri,
        "scope": scope, "response_type": "code", "csrf_token": csrf_token,
    }
    if code_challenge:
        form_data["code_challenge"] = code_challenge
        form_data["code_challenge_method"] = code_challenge_method

    auth_resp = await client.post("/oauth/authorize", data=form_data, follow_redirects=False)
    mock_valkey.get = original_get
    assert auth_resp.status_code == 302
    code = parse_qs(urlparse(auth_resp.headers["location"]).query)["code"][0]
    return code


async def test_create_app(app_client, mock_valkey):
    resp = await app_client.post("/api/v1/apps", json={
        "client_name": "TestApp", "redirect_uris": "http://localhost/callback", "scopes": "read write"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "client_id" in data
    assert "client_secret" in data


async def test_create_app_form_urlencoded(app_client, mock_valkey):
    """Mastodon clients (Feather, Ivory, etc.) send form-urlencoded."""
    resp = await app_client.post(
        "/api/v1/apps",
        data={
            "client_name": "Feather",
            "redirect_uris": "feather://callback",
            "scopes": "read write follow push",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Feather"
    assert "client_id" in data
    assert "client_secret" in data
    assert data["redirect_uri"] == "feather://callback"


async def test_authorize_not_logged_in(app_client, mock_valkey):
    app_resp = await app_client.post("/api/v1/apps", json={
        "client_name": "TestApp", "redirect_uris": "http://localhost/callback"
    })
    client_id = app_resp.json()["client_id"]
    resp = await app_client.get("/oauth/authorize", params={
        "response_type": "code", "client_id": client_id,
        "redirect_uri": "http://localhost/callback", "scope": "read"
    }, follow_redirects=False)
    assert resp.status_code == 200  # Login HTML


async def test_authorize_logged_in_shows_consent(authed_client, mock_valkey):
    """H-1: ログイン済みでも同意画面を表示する (自動認可廃止)。"""
    app_resp = await authed_client.post("/api/v1/apps", json={
        "client_name": "TestApp", "redirect_uris": "http://localhost/callback"
    })
    client_id = app_resp.json()["client_id"]
    resp = await authed_client.get("/oauth/authorize", params={
        "response_type": "code", "client_id": client_id,
        "redirect_uri": "http://localhost/callback", "scope": "read"
    }, follow_redirects=False)
    assert resp.status_code == 200
    assert "Authorize" in resp.text


async def test_token_authorization_code(authed_client, mock_valkey):
    app_resp = await authed_client.post("/api/v1/apps", json={
        "client_name": "TestApp", "redirect_uris": "http://localhost/callback"
    })
    app_data = app_resp.json()
    code = await _authorize_via_consent(
        authed_client, mock_valkey,
        client_id=app_data["client_id"], redirect_uri="http://localhost/callback",
    )
    token_resp = await authed_client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code,
        "client_id": app_data["client_id"], "client_secret": app_data["client_secret"],
        "redirect_uri": "http://localhost/callback",
    })
    assert token_resp.status_code == 200
    assert "access_token" in token_resp.json()


async def test_token_invalid_code(authed_client, mock_valkey):
    app_resp = await authed_client.post("/api/v1/apps", json={
        "client_name": "T", "redirect_uris": "http://localhost/callback"
    })
    app_data = app_resp.json()
    resp = await authed_client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": "invalid",
        "client_id": app_data["client_id"], "client_secret": app_data["client_secret"],
    })
    assert resp.status_code == 400


async def test_token_client_credentials(app_client, mock_valkey):
    app_resp = await app_client.post("/api/v1/apps", json={
        "client_name": "T", "redirect_uris": "http://localhost/callback"
    })
    d = app_resp.json()
    resp = await app_client.post("/oauth/token", data={
        "grant_type": "client_credentials",
        "client_id": d["client_id"], "client_secret": d["client_secret"],
    })
    assert resp.status_code == 200
    assert resp.json()["token_type"] == "Bearer"


async def test_pkce_s256(authed_client, mock_valkey):
    app_resp = await authed_client.post("/api/v1/apps", json={
        "client_name": "PKCE", "redirect_uris": "http://localhost/callback"
    })
    d = app_resp.json()
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    code = await _authorize_via_consent(
        authed_client, mock_valkey,
        client_id=d["client_id"], redirect_uri="http://localhost/callback",
        code_challenge=challenge, code_challenge_method="S256",
    )
    resp = await authed_client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code,
        "client_id": d["client_id"], "client_secret": d["client_secret"],
        "redirect_uri": "http://localhost/callback", "code_verifier": verifier,
    })
    assert resp.status_code == 200


async def test_pkce_wrong_verifier(authed_client, mock_valkey):
    app_resp = await authed_client.post("/api/v1/apps", json={
        "client_name": "PKCE", "redirect_uris": "http://localhost/callback"
    })
    d = app_resp.json()
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    code = await _authorize_via_consent(
        authed_client, mock_valkey,
        client_id=d["client_id"], redirect_uri="http://localhost/callback",
        code_challenge=challenge, code_challenge_method="S256",
    )
    resp = await authed_client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code,
        "client_id": d["client_id"], "client_secret": d["client_secret"],
        "redirect_uri": "http://localhost/callback", "code_verifier": "wrong-verifier",
    })
    assert resp.status_code == 400


async def test_revoke_token(authed_client, mock_valkey):
    app_resp = await authed_client.post("/api/v1/apps", json={
        "client_name": "Rev", "redirect_uris": "http://localhost/callback"
    })
    d = app_resp.json()
    code = await _authorize_via_consent(
        authed_client, mock_valkey,
        client_id=d["client_id"], redirect_uri="http://localhost/callback",
    )
    token_resp = await authed_client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code,
        "client_id": d["client_id"], "client_secret": d["client_secret"],
        "redirect_uri": "http://localhost/callback",
    })
    token = token_resp.json()["access_token"]
    revoke_resp = await authed_client.post("/oauth/revoke", data={
        "token": token, "client_id": d["client_id"], "client_secret": d["client_secret"],
    })
    assert revoke_resp.status_code == 200
