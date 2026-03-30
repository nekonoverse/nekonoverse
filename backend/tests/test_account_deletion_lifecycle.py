"""アカウント削除ライフサイクル統合テスト。

予約→期限切れ→自動削除、キャンセル、管理者即時削除、ユーザー名再利用防止、
AP Tombstone の各フローを一気通貫でテストする。
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import make_note, make_remote_actor

pytestmark = pytest.mark.usefixtures("seed_roles")


# ── Helpers ──────────────────────────────────────────────────────────────────


def authed_client_for(app_client, mock_valkey, user):
    mock_valkey.get = AsyncMock(return_value=str(user.id))
    app_client.cookies.set("nekonoverse_session", "test-session-id")
    return app_client


async def make_admin_user(db):
    from app.services.user_service import create_user

    user = await create_user(
        db, "adminlife", "admin-life@example.com", "password1234", display_name="Admin"
    )
    user.role = "admin"
    await db.flush()
    return user


# ── 予約 → 期限切れ → 自動削除 ──────────────────────────────────────────


async def test_request_expire_auto_delete(db, test_user, mock_valkey):
    """削除予約 → 猶予期間経過 → process_expired_deletions で自動削除。"""
    from app.services.account_deletion_service import (
        process_expired_deletions,
        request_deletion,
    )

    # 1. 削除予約
    scheduled_at = await request_deletion(db, test_user)
    await db.flush()
    assert test_user.actor.is_deletion_pending is True
    assert test_user.actor.is_suspended is True

    # 2. 猶予期間内は処理されない
    count = await process_expired_deletions(db)
    assert count == 0

    # 3. 猶予期間を過去に変更して期限切れを模擬
    test_user.actor.deletion_scheduled_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db.flush()

    # 4. 自動削除実行
    with patch(
        "app.services.follow_service.get_follower_inboxes",
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        "app.services.delivery_service.enqueue_delivery",
        new_callable=AsyncMock,
    ), patch(
        "app.services.drive_service.delete_drive_file",
        new_callable=AsyncMock,
    ):
        count = await process_expired_deletions(db)
    assert count == 1

    await db.refresh(test_user.actor)
    assert test_user.actor.is_deleted is True
    assert test_user.actor.deletion_scheduled_at is None


# ── 予約 → キャンセル → 正常復帰 ────────────────────────────────────────


async def test_request_cancel_restore(db, test_user, mock_valkey):
    """削除予約 → キャンセル → 通常状態に復帰。"""
    from app.services.account_deletion_service import cancel_deletion, request_deletion

    # 1. 削除予約
    await request_deletion(db, test_user)
    await db.flush()
    assert test_user.actor.is_deletion_pending is True

    # 2. キャンセル
    await cancel_deletion(db, test_user)
    await db.flush()

    await db.refresh(test_user.actor)
    assert test_user.actor.is_deletion_pending is False
    assert test_user.actor.is_suspended is False
    assert test_user.actor.deletion_scheduled_at is None
    assert test_user.actor.suspended_at is None


# ── 管理者即時削除 ───────────────────────────────────────────────────────


async def test_admin_force_delete_lifecycle(db, mock_valkey):
    """管理者が即時削除すると全データがクリーンアップされる。"""
    from app.services.account_deletion_service import admin_force_delete
    from app.services.user_service import create_user

    admin = await make_admin_user(db)
    target = await create_user(
        db, "target_life", "target-life@example.com", "password1234",
        display_name="Target"
    )
    note = await make_note(db, target.actor, content="Will be deleted")
    await db.flush()

    with patch(
        "app.services.follow_service.get_follower_inboxes",
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        "app.services.delivery_service.enqueue_delivery",
        new_callable=AsyncMock,
    ), patch(
        "app.services.drive_service.delete_drive_file",
        new_callable=AsyncMock,
    ):
        await admin_force_delete(db, target.actor, admin, "テスト削除")
    await db.flush()

    await db.refresh(target.actor)
    await db.refresh(target)
    await db.refresh(note)

    assert target.actor.is_deleted is True
    assert note.deleted_at is not None
    assert target.email.endswith("@deleted.invalid")
    assert target.password_hash == "!deleted"


# ── ユーザー名再利用防止 ─────────────────────────────────────────────────


async def test_username_not_reusable_after_deletion(db, mock_valkey):
    """削除済みユーザーのユーザー名で再登録できない。"""
    from app.services.account_deletion_service import admin_force_delete
    from app.services.user_service import create_user

    admin = await make_admin_user(db)
    target = await create_user(
        db, "reuseme", "reuse@example.com", "password1234", display_name="Reuse"
    )
    await db.flush()

    with patch(
        "app.services.follow_service.get_follower_inboxes",
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        "app.services.delivery_service.enqueue_delivery",
        new_callable=AsyncMock,
    ), patch(
        "app.services.drive_service.delete_drive_file",
        new_callable=AsyncMock,
    ):
        await admin_force_delete(db, target.actor, admin, "テスト")
    await db.flush()

    # 同じユーザー名で再登録を試みる
    with pytest.raises(Exception):
        await create_user(
            db, "reuseme", "newreuse@example.com", "password1234",
            display_name="New Reuse"
        )


# ── 削除済みアクターの AP エンドポイント → 410 + Tombstone ───────────────


async def test_deleted_actor_returns_tombstone(db, app_client, mock_valkey):
    """削除済みアクターの AP エンドポイントは 410 + Tombstone JSON-LD を返す。"""
    from app.services.user_service import create_user

    user = await create_user(
        db, "tombuser", "tomb@example.com", "password1234", display_name="Tomb"
    )
    user.actor.deleted_at = datetime.now(timezone.utc)
    await db.flush()

    # AP リクエスト (application/activity+json)
    resp = await app_client.get(
        "/users/tombuser",
        headers={"accept": "application/activity+json"},
    )
    assert resp.status_code == 410
    data = resp.json()
    assert data["type"] == "Tombstone"
    assert "tombuser" in data["id"]

    # ブラウザリクエスト
    resp = await app_client.get(
        "/users/tombuser",
        headers={"accept": "text/html"},
    )
    assert resp.status_code == 410
