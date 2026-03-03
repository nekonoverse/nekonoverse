from unittest.mock import AsyncMock


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


async def test_verify_credentials_no_session(app_client, mock_valkey):
    resp = await app_client.get("/api/v1/accounts/verify_credentials")
    assert resp.status_code == 401


async def test_register_returns_role(app_client, mock_valkey):
    resp = await app_client.post("/api/v1/accounts", json={
        "username": "roleuser", "email": "role@example.com", "password": "password1234"
    })
    assert resp.status_code == 201
    assert resp.json()["role"] == "user"
