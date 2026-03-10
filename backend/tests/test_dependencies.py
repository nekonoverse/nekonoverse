"""Tests for app.dependencies (session auth middleware)."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.dependencies import get_current_user, get_optional_user


@pytest.fixture
def mock_request():
    """Create a mock request with configurable cookies."""
    request = AsyncMock()
    request.cookies = {}
    return request


# ── get_current_user ──


async def test_get_current_user_success(db, test_user, mock_request, mock_valkey):
    mock_request.cookies = {"nekonoverse_session": "valid-session"}
    mock_valkey.get = AsyncMock(return_value=str(test_user.id))

    user = await get_current_user(mock_request, db)
    assert user.id == test_user.id


async def test_get_current_user_no_cookie(db, mock_request, mock_valkey):
    mock_request.cookies = {}

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(mock_request, db)

    assert exc_info.value.status_code == 401
    assert "Not authenticated" in exc_info.value.detail


async def test_get_current_user_expired_session(db, mock_request, mock_valkey):
    mock_request.cookies = {"nekonoverse_session": "expired-session"}
    mock_valkey.get = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(mock_request, db)

    assert exc_info.value.status_code == 401
    assert "expired" in exc_info.value.detail.lower()


async def test_get_current_user_deleted_user(db, mock_request, mock_valkey):
    fake_user_id = uuid.uuid4()
    mock_request.cookies = {"nekonoverse_session": "orphan-session"}
    mock_valkey.get = AsyncMock(return_value=str(fake_user_id))

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(mock_request, db)

    assert exc_info.value.status_code == 401
    assert "not found" in exc_info.value.detail.lower()


# ── get_optional_user ──


async def test_get_optional_user_no_cookie(db, mock_request, mock_valkey):
    mock_request.cookies = {}

    user = await get_optional_user(mock_request, db)
    assert user is None


async def test_get_optional_user_valid_session(db, test_user, mock_request, mock_valkey):
    mock_request.cookies = {"nekonoverse_session": "valid-session"}
    mock_valkey.get = AsyncMock(return_value=str(test_user.id))

    user = await get_optional_user(mock_request, db)
    assert user is not None
    assert user.id == test_user.id


async def test_get_optional_user_expired_session(db, mock_request, mock_valkey):
    mock_request.cookies = {"nekonoverse_session": "expired-session"}
    mock_valkey.get = AsyncMock(return_value=None)

    user = await get_optional_user(mock_request, db)
    assert user is None


async def test_get_optional_user_deleted_user(db, mock_request, mock_valkey):
    fake_user_id = uuid.uuid4()
    mock_request.cookies = {"nekonoverse_session": "orphan-session"}
    mock_valkey.get = AsyncMock(return_value=str(fake_user_id))

    user = await get_optional_user(mock_request, db)
    assert user is None


# ── Suspended user checks ──


async def test_get_current_user_suspended(db, test_user, mock_request, mock_valkey):
    """A suspended user should receive 403 and have their session deleted."""
    from datetime import datetime, timezone

    # Suspend the user's actor
    test_user.actor.suspended_at = datetime.now(timezone.utc)
    await db.flush()

    mock_request.cookies = {"nekonoverse_session": "suspended-session"}
    mock_valkey.get = AsyncMock(return_value=str(test_user.id))

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(mock_request, db)

    assert exc_info.value.status_code == 403
    assert "suspended" in exc_info.value.detail.lower()
    # Session should be invalidated
    mock_valkey.delete.assert_called_with("session:suspended-session")


async def test_get_optional_user_suspended(db, test_user, mock_request, mock_valkey):
    """A suspended user should be treated as unauthenticated (return None)."""
    from datetime import datetime, timezone

    test_user.actor.suspended_at = datetime.now(timezone.utc)
    await db.flush()

    mock_request.cookies = {"nekonoverse_session": "suspended-session"}
    mock_valkey.get = AsyncMock(return_value=str(test_user.id))

    user = await get_optional_user(mock_request, db)
    assert user is None
    mock_valkey.delete.assert_called_with("session:suspended-session")


# ── invalidate_user_sessions ──


async def test_invalidate_user_sessions(mock_valkey, test_user):
    """invalidate_user_sessions should scan and delete matching sessions."""
    from app.services.moderation_service import invalidate_user_sessions

    user_id = test_user.id
    other_id = uuid.uuid4()

    # Simulate two scan iterations: first returns 2 keys, second returns 1
    mock_valkey.scan = AsyncMock(side_effect=[
        (42, ["session:aaa", "session:bbb"]),  # cursor=42, more to scan
        (0, ["session:ccc"]),                   # cursor=0, done
    ])

    async def get_side_effect(key):
        mapping = {
            "session:aaa": str(user_id),     # belongs to target user
            "session:bbb": str(other_id),    # belongs to a different user
            "session:ccc": str(user_id),     # belongs to target user
        }
        return mapping.get(key)

    mock_valkey.get = AsyncMock(side_effect=get_side_effect)

    deleted = await invalidate_user_sessions(user_id)
    assert deleted == 2  # aaa and ccc belong to the target user

    # bbb should NOT have been deleted
    delete_calls = [call.args[0] for call in mock_valkey.delete.call_args_list]
    assert "session:aaa" in delete_calls
    assert "session:ccc" in delete_calls
    assert "session:bbb" not in delete_calls
