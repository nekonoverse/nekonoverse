import hashlib
import base64
import secrets
from urllib.parse import parse_qs, urlparse


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


async def test_authorize_logged_in_redirects(authed_client, mock_valkey):
    app_resp = await authed_client.post("/api/v1/apps", json={
        "client_name": "TestApp", "redirect_uris": "http://localhost/callback"
    })
    client_id = app_resp.json()["client_id"]
    resp = await authed_client.get("/oauth/authorize", params={
        "response_type": "code", "client_id": client_id,
        "redirect_uri": "http://localhost/callback", "scope": "read"
    }, follow_redirects=False)
    assert resp.status_code == 302
    assert "code=" in resp.headers["location"]


async def test_token_authorization_code(authed_client, mock_valkey):
    app_resp = await authed_client.post("/api/v1/apps", json={
        "client_name": "TestApp", "redirect_uris": "http://localhost/callback"
    })
    app_data = app_resp.json()
    auth_resp = await authed_client.get("/oauth/authorize", params={
        "response_type": "code", "client_id": app_data["client_id"],
        "redirect_uri": "http://localhost/callback", "scope": "read"
    }, follow_redirects=False)
    code = parse_qs(urlparse(auth_resp.headers["location"]).query)["code"][0]
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
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    auth_resp = await authed_client.get("/oauth/authorize", params={
        "response_type": "code", "client_id": d["client_id"],
        "redirect_uri": "http://localhost/callback", "scope": "read",
        "code_challenge": challenge, "code_challenge_method": "S256",
    }, follow_redirects=False)
    code = parse_qs(urlparse(auth_resp.headers["location"]).query)["code"][0]
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
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    auth_resp = await authed_client.get("/oauth/authorize", params={
        "response_type": "code", "client_id": d["client_id"],
        "redirect_uri": "http://localhost/callback",
        "code_challenge": challenge, "code_challenge_method": "S256",
    }, follow_redirects=False)
    code = parse_qs(urlparse(auth_resp.headers["location"]).query)["code"][0]
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
    auth_resp = await authed_client.get("/oauth/authorize", params={
        "response_type": "code", "client_id": d["client_id"],
        "redirect_uri": "http://localhost/callback", "scope": "read"
    }, follow_redirects=False)
    code = parse_qs(urlparse(auth_resp.headers["location"]).query)["code"][0]
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
