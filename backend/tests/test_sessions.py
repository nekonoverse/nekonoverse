"""Tests for session management and login history endpoints."""

from unittest.mock import AsyncMock

from sqlalchemy import select

from app.models.login_history import LoginHistory


async def test_login_records_history(app_client, test_user, mock_valkey, db):
    """Successful login should create a login_history record."""
    resp = await app_client.post("/api/v1/auth/login", json={
        "username": "testuser", "password": "password1234"
    })
    assert resp.status_code == 200

    result = await db.execute(
        select(LoginHistory).where(
            LoginHistory.user_id == test_user.id,
            LoginHistory.method == "password",
            LoginHistory.success == True,  # noqa: E712
        )
    )
    entry = result.scalar_one_or_none()
    assert entry is not None
    assert entry.ip_address == "127.0.0.1"


async def test_login_creates_session_metadata(app_client, test_user, mock_valkey):
    """Login should call hset for session metadata."""
    resp = await app_client.post("/api/v1/auth/login", json={
        "username": "testuser", "password": "password1234"
    })
    assert resp.status_code == 200
    mock_valkey.hset.assert_called()
    mock_valkey.sadd.assert_called()


async def test_list_sessions(authed_client, test_user, mock_valkey):
    """GET /auth/sessions returns session list."""
    mock_valkey.smembers = AsyncMock(return_value={"test-session-id"})
    mock_valkey.exists = AsyncMock(return_value=True)
    mock_valkey.hgetall = AsyncMock(return_value={
        "user_id": str(test_user.id),
        "ip": "127.0.0.1",
        "user_agent": "TestAgent",
        "created_at": "2026-03-21T00:00:00+00:00",
    })

    resp = await authed_client.get("/api/v1/auth/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["session_id"] == "test-session-id"
    assert data[0]["is_current"] is True
    assert data[0]["ip"] == "127.0.0.1"


async def test_revoke_other_session(authed_client, test_user, mock_valkey):
    """DELETE /auth/sessions/{id} should revoke a non-current session."""
    other_sid = "other-session-id"
    mock_valkey.get = AsyncMock(return_value=str(test_user.id))

    resp = await authed_client.delete(f"/api/v1/auth/sessions/{other_sid}")
    assert resp.status_code == 200
    mock_valkey.delete.assert_any_call(f"session:{other_sid}")


async def test_revoke_current_session_rejected(authed_client, mock_valkey):
    """Cannot revoke the session you're currently using."""
    resp = await authed_client.delete("/api/v1/auth/sessions/test-session-id")
    assert resp.status_code == 400
    assert "current session" in resp.json()["detail"]


async def test_revoke_other_users_session(authed_client, test_user, mock_valkey):
    """Cannot revoke a session belonging to another user."""
    import uuid as _uuid

    other_user_id = str(_uuid.uuid4())
    user_id = str(test_user.id)

    # get_current_user reads session:{cookie} → user_id (first call)
    # delete_session reads session:{target} → other_user_id (second call)
    call_count = 0

    async def side_effect(key):
        nonlocal call_count
        call_count += 1
        if key == "session:test-session-id":
            return user_id
        return other_user_id

    mock_valkey.get = AsyncMock(side_effect=side_effect)

    resp = await authed_client.delete("/api/v1/auth/sessions/foreign-session")
    assert resp.status_code == 404


async def test_login_history_endpoint(authed_client, test_user, mock_valkey, db):
    """GET /auth/login_history returns recorded entries."""
    from app.services.session_service import record_login

    await record_login(db, test_user.id, "10.0.0.1", "TestBrowser", "password")
    await record_login(db, test_user.id, "10.0.0.2", "TestBrowser2", "passkey")
    await db.commit()

    resp = await authed_client.get("/api/v1/auth/login_history")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["ip_address"] == "10.0.0.2"  # newest first
    assert data[0]["method"] == "passkey"
    assert data[1]["ip_address"] == "10.0.0.1"
    assert data[1]["method"] == "password"


async def test_login_history_limit(authed_client, test_user, mock_valkey, db):
    """GET /auth/login_history respects limit parameter."""
    from app.services.session_service import record_login

    for i in range(5):
        await record_login(db, test_user.id, f"10.0.0.{i}", None, "password")
    await db.commit()

    resp = await authed_client.get("/api/v1/auth/login_history?limit=3")
    assert resp.status_code == 200
    assert len(resp.json()) == 3
