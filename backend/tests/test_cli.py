"""Tests for app.cli (management CLI)."""

import argparse
import sys
import uuid
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


# ── _detect_focal_points: SQL 三値論理回帰 ──


async def test_detect_focal_points_query_includes_null_version_rows(db, test_user, mock_valkey):
    """focal_detect_version IS NULL の DriveFile が `!= 'manual'` フィルタで除外されないこと (#1022 回帰)。

    SQL の `column != 'manual'` は column IS NULL の行で NULL (=UNKNOWN) を返し
    WHERE で除外される三値論理問題があるため、IS NULL を or_ で明示的に許可する必要がある。
    バグがある状態だと未検出 (NULL) の画像がそもそも処理対象に入らない。
    """
    from sqlalchemy import select

    from app.cli import _drive_file_pending_focal_conditions
    from app.models.drive_file import DriveFile

    # NULL 版の画像 (まだ検出されていない)
    df_null = DriveFile(
        owner_id=test_user.id,
        s3_key=f"uploads/{uuid.uuid4().hex}/null.png",
        filename="null.png",
        mime_type="image/png",
        size_bytes=1024,
        focal_detect_version=None,
    )
    # manual 版の画像 (除外されるべき)
    df_manual = DriveFile(
        owner_id=test_user.id,
        s3_key=f"uploads/{uuid.uuid4().hex}/manual.png",
        filename="manual.png",
        mime_type="image/png",
        size_bytes=1024,
        focal_detect_version="manual",
    )
    # 旧バージョン (再検出対象)
    df_old = DriveFile(
        owner_id=test_user.id,
        s3_key=f"uploads/{uuid.uuid4().hex}/old.png",
        filename="old.png",
        mime_type="image/png",
        size_bytes=1024,
        focal_detect_version="old-version-1",
    )
    # 現バージョン (スキップ)
    df_current = DriveFile(
        owner_id=test_user.id,
        s3_key=f"uploads/{uuid.uuid4().hex}/current.png",
        filename="current.png",
        mime_type="image/png",
        size_bytes=1024,
        focal_detect_version="current-version-2",
    )
    db.add_all([df_null, df_manual, df_old, df_current])
    await db.commit()

    # CLI 実装側のヘルパを呼び出して WHERE 条件を取得 (実装が変わればテストも追従)
    conditions = _drive_file_pending_focal_conditions("current-version-2")
    rows = await db.execute(select(DriveFile).where(*conditions))
    target_ids = {r.id for r in rows.scalars().all()}

    # NULL と old は対象、manual と current は除外
    assert df_null.id in target_ids, "NULL 版が処理対象に含まれていない (三値論理バグの再発)"
    assert df_old.id in target_ids
    assert df_manual.id not in target_ids
    assert df_current.id not in target_ids


async def test_detect_focal_points_note_attachment_includes_null_version_rows(db, test_user, mock_valkey):
    """NoteAttachment 側も同じ三値論理問題から守られていることの回帰テスト (#1022)。

    DriveFile 側と対称な NULL 行除外バグが NoteAttachment 側にも存在していたため、
    片肺修正ではなく両系列でテストカバーする。
    """
    from sqlalchemy import select

    from tests.conftest import make_note

    from app.cli import _note_attachment_pending_focal_conditions
    from app.models.note_attachment import NoteAttachment

    # NoteAttachment は note_id FK 必須なので Note を 1 件用意
    actor_id = test_user.actor_id
    from app.models.actor import Actor
    actor = (await db.execute(select(Actor).where(Actor.id == actor_id))).scalar_one()
    note = await make_note(db, actor)
    await db.commit()

    common = {
        "note_id": note.id,
        "remote_url": "https://remote.example/img.png",
        "remote_mime_type": "image/png",
    }
    att_null = NoteAttachment(**common, position=0, focal_detect_version=None)
    att_manual = NoteAttachment(**common, position=1, focal_detect_version="manual")
    att_old = NoteAttachment(**common, position=2, focal_detect_version="old-1")
    att_current = NoteAttachment(**common, position=3, focal_detect_version="current-2")
    db.add_all([att_null, att_manual, att_old, att_current])
    await db.commit()

    conditions = _note_attachment_pending_focal_conditions("current-2")
    rows = await db.execute(select(NoteAttachment).where(*conditions))
    target_ids = {r.id for r in rows.scalars().all()}

    assert att_null.id in target_ids, "NULL 版が処理対象に含まれていない (三値論理バグの再発)"
    assert att_old.id in target_ids
    assert att_manual.id not in target_ids
    assert att_current.id not in target_ids
