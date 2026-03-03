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
