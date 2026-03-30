"""Tests for session_service: session CRUD, login history recording."""

from unittest.mock import AsyncMock

from sqlalchemy import select

from app.models.login_history import LoginHistory
from app.services.session_service import (
    cleanup_session_metadata,
    create_session_with_metadata,
    delete_session,
    get_login_history,
    list_user_sessions,
    record_login,
)

# -- create_session_with_metadata --


async def test_create_session_with_metadata(mock_valkey, test_user):
    mock_valkey.hset = AsyncMock(return_value=True)
    mock_valkey.sadd = AsyncMock(return_value=1)

    await create_session_with_metadata(
        mock_valkey, test_user.id, "sess1", "127.0.0.1", "Mozilla/5.0"
    )

    mock_valkey.set.assert_called_once()
    # set の第1引数が session:sess1 であること
    args = mock_valkey.set.call_args
    assert args[0][0] == "session:sess1"
    assert args[0][1] == str(test_user.id)

    mock_valkey.hset.assert_called_once()
    mock_valkey.sadd.assert_called_once()


# -- list_user_sessions --


async def test_list_user_sessions(mock_valkey, test_user):
    mock_valkey.smembers = AsyncMock(return_value={"sess1"})
    mock_valkey.exists = AsyncMock(return_value=True)
    mock_valkey.hgetall = AsyncMock(return_value={
        "user_id": str(test_user.id),
        "ip": "127.0.0.1",
        "user_agent": "Mozilla/5.0",
        "created_at": "2026-03-30T00:00:00+00:00",
    })

    sessions = await list_user_sessions(mock_valkey, test_user.id)

    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "sess1"
    assert sessions[0]["ip"] == "127.0.0.1"
    assert sessions[0]["user_agent"] == "Mozilla/5.0"


# -- delete_session --


async def test_delete_session(mock_valkey, test_user):
    mock_valkey.get = AsyncMock(return_value=str(test_user.id))
    mock_valkey.srem = AsyncMock(return_value=1)

    result = await delete_session(mock_valkey, test_user.id, "sess1")

    assert result is True
    mock_valkey.delete.assert_any_call("session:sess1")
    mock_valkey.delete.assert_any_call("session_meta:sess1")
    mock_valkey.srem.assert_called_once()


# -- cleanup_session_metadata --


async def test_cleanup_session_metadata(mock_valkey, test_user):
    mock_valkey.srem = AsyncMock(return_value=1)

    await cleanup_session_metadata(mock_valkey, test_user.id, "sess1")

    mock_valkey.delete.assert_called_once_with("session_meta:sess1")
    mock_valkey.srem.assert_called_once_with(f"user_sessions:{test_user.id}", "sess1")


# -- record_login --


async def test_record_login(db, test_user, mock_valkey):
    await record_login(db, test_user.id, "192.168.1.1", "TestBrowser", "password")

    result = await db.execute(
        select(LoginHistory).where(LoginHistory.user_id == test_user.id)
    )
    entry = result.scalar_one_or_none()
    assert entry is not None
    assert entry.ip_address == "192.168.1.1"
    assert entry.user_agent == "TestBrowser"
    assert entry.method == "password"
    assert entry.success is True


# -- get_login_history --


async def test_get_login_history(db, test_user, mock_valkey):
    await record_login(db, test_user.id, "10.0.0.1", "Browser1", "password")
    await record_login(db, test_user.id, "10.0.0.2", "Browser2", "passkey")

    history = await get_login_history(db, test_user.id)

    assert len(history) == 2
    # 新しい順で返される
    assert history[0].ip_address == "10.0.0.2"
    assert history[0].method == "passkey"
    assert history[1].ip_address == "10.0.0.1"
    assert history[1].method == "password"


async def test_get_login_history_empty(db, test_user, mock_valkey):
    history = await get_login_history(db, test_user.id)
    assert history == []
