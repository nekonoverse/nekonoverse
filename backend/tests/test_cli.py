"""Tests for app.cli (management CLI)."""

import argparse
import sys
from unittest.mock import AsyncMock, patch

import pytest

from app.cli import _create_admin, main

# ── _create_admin ──


async def test_create_admin_success(db, mock_valkey):
    args = argparse.Namespace(
        username="adminuser",
        email="admin@example.com",
        password="securepassword1234",
        display_name="Admin",
    )

    with patch("app.cli.async_session") as mock_session_ctx, patch("app.cli.engine") as mock_engine:
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_engine.dispose = AsyncMock()

        await _create_admin(args)

    from sqlalchemy import select

    from app.models.user import User

    result = await db.execute(select(User).where(User.email == "admin@example.com"))
    user = result.scalar_one_or_none()
    assert user is not None
    assert user.role == "admin"


async def test_create_admin_duplicate_exits(db, test_user, mock_valkey):
    args = argparse.Namespace(
        username="testuser",  # Already created by test_user fixture
        email="another@example.com",
        password="password1234",
        display_name=None,
    )

    with (
        patch("app.cli.async_session") as mock_session_ctx,
        patch("app.cli.engine") as mock_engine,
    ):
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_engine.dispose = AsyncMock()

        with pytest.raises(SystemExit) as exc_info:
            await _create_admin(args)

        assert exc_info.value.code == 1


async def test_create_admin_no_display_name(db, mock_valkey):
    args = argparse.Namespace(
        username="nodisplay",
        email="nodisplay@example.com",
        password="password1234",
        display_name=None,
    )

    with patch("app.cli.async_session") as mock_session_ctx, patch("app.cli.engine") as mock_engine:
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_engine.dispose = AsyncMock()

        await _create_admin(args)

    from sqlalchemy import select

    from app.models.user import User

    result = await db.execute(select(User).where(User.email == "nodisplay@example.com"))
    user = result.scalar_one_or_none()
    assert user is not None
    assert user.role == "admin"


# ── main (argparse) ──


def test_main_no_command_exits():
    with patch("sys.argv", ["nekonoverse"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1


def test_main_create_admin_calls_async(monkeypatch):
    test_args = [
        "nekonoverse",
        "create-admin",
        "--username", "testadmin",
        "--email", "testadmin@example.com",
        "--password", "password1234",
    ]
    monkeypatch.setattr(sys, "argv", test_args)

    with patch("app.cli.asyncio.run") as mock_run:
        main()

    mock_run.assert_called_once()
    coro = mock_run.call_args[0][0]
    coro.close()


def test_main_create_admin_with_display_name(monkeypatch):
    test_args = [
        "nekonoverse",
        "create-admin",
        "--username", "testadmin2",
        "--email", "testadmin2@example.com",
        "--password", "password1234",
        "--display-name", "Test Admin",
    ]
    monkeypatch.setattr(sys, "argv", test_args)

    with patch("app.cli.asyncio.run") as mock_run:
        main()

    mock_run.assert_called_once()
    coro = mock_run.call_args[0][0]
    coro.close()


# ── _reset_password ──


async def test_reset_password_success(db, test_user, mock_valkey):
    args = argparse.Namespace(
        username="testuser",
        password="newpassword1234",
    )

    with patch("app.cli.async_session") as mock_session_ctx, patch("app.cli.engine") as mock_engine:
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_engine.dispose = AsyncMock()

        from app.cli import _reset_password
        await _reset_password(args)

    from app.services.user_service import authenticate_user
    user = await authenticate_user(db, "testuser", "newpassword1234")
    assert user is not None


async def test_reset_password_user_not_found(db, mock_valkey):
    args = argparse.Namespace(
        username="nonexistent",
        password="newpassword1234",
    )

    with (
        patch("app.cli.async_session") as mock_session_ctx,
        patch("app.cli.engine") as mock_engine,
    ):
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_engine.dispose = AsyncMock()

        from app.cli import _reset_password
        with pytest.raises(SystemExit) as exc_info:
            await _reset_password(args)
        assert exc_info.value.code == 1


def test_main_reset_password_calls_async(monkeypatch):
    test_args = [
        "nekonoverse",
        "reset-password",
        "--username", "testuser",
        "--password", "newpassword1234",
    ]
    monkeypatch.setattr(sys, "argv", test_args)

    with patch("app.cli.asyncio.run") as mock_run:
        main()

    mock_run.assert_called_once()
    coro = mock_run.call_args[0][0]
    coro.close()
