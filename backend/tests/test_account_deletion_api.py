"""アカウント削除 API エンドポイントのテスト。"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.usefixtures("seed_roles")


# ── Helpers ──────────────────────────────────────────────────────────────────


async def make_admin_user(db):
    from app.services.user_service import create_user

    user = await create_user(
        db, "adminuser", "admin@example.com", "password1234", display_name="Admin"
    )
    user.role = "admin"
    await db.flush()
    return user


async def make_moderator_user(db):
    from app.services.user_service import create_user

    user = await create_user(
        db, "moduser", "mod@example.com", "password1234", display_name="Moderator"
    )
    user.role = "moderator"
    await db.flush()
    return user


def authed_client_for(app_client, mock_valkey, user):
    mock_valkey.get = AsyncMock(return_value=str(user.id))
    app_client.cookies.set("nekonoverse_session", "test-session-id")
    return app_client


# ── POST /api/v1/auth/delete_account ─────────────────────────────────────


async def test_delete_account_success(db, app_client, mock_valkey, test_user):
    """パスワード確認後にアカウント削除を予約できる。"""
    client = authed_client_for(app_client, mock_valkey, test_user)

    resp = await client.post(
        "/api/v1/auth/delete_account", json={"password": "password1234"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "deletion_scheduled_at" in data

    await db.refresh(test_user.actor)
    assert test_user.actor.is_deletion_pending is True
    assert test_user.actor.is_suspended is True


async def test_delete_account_wrong_password(db, app_client, mock_valkey, test_user):
    """パスワードが間違っている場合は 401。"""
    client = authed_client_for(app_client, mock_valkey, test_user)

    resp = await client.post(
        "/api/v1/auth/delete_account", json={"password": "wrongpassword"}
    )
    assert resp.status_code == 401
    assert "Invalid password" in resp.json()["detail"]


async def test_delete_account_unauthenticated(app_client):
    """未認証の場合は 401。"""
    resp = await app_client.post(
        "/api/v1/auth/delete_account", json={"password": "password1234"}
    )
    assert resp.status_code == 401


async def test_delete_account_already_pending(db, app_client, mock_valkey, test_user):
    """既に削除予約中の場合は 422。"""
    client = authed_client_for(app_client, mock_valkey, test_user)

    # 1回目: 成功
    resp = await client.post(
        "/api/v1/auth/delete_account", json={"password": "password1234"}
    )
    assert resp.status_code == 200

    # 2回目: get_current_user で is_deletion_pending → 403 (X-Deletion-Pending)
    await db.refresh(test_user.actor)
    resp = await client.post(
        "/api/v1/auth/delete_account", json={"password": "password1234"}
    )
    assert resp.status_code == 403
    assert resp.headers.get("x-deletion-pending") == "true"


# ── POST /api/v1/auth/cancel_deletion ────────────────────────────────────


async def test_cancel_deletion_success(db, app_client, mock_valkey, test_user):
    """削除予約をキャンセルできる。"""
    client = authed_client_for(app_client, mock_valkey, test_user)

    # まず削除を予約
    resp = await client.post(
        "/api/v1/auth/delete_account", json={"password": "password1234"}
    )
    assert resp.status_code == 200
    await db.refresh(test_user.actor)

    # キャンセル
    resp = await client.post(
        "/api/v1/auth/cancel_deletion", json={"password": "password1234"}
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    await db.refresh(test_user.actor)
    assert test_user.actor.is_deletion_pending is False
    assert test_user.actor.is_suspended is False


async def test_cancel_deletion_wrong_password(db, app_client, mock_valkey, test_user):
    """キャンセル時のパスワードが間違っている場合は 401。"""
    client = authed_client_for(app_client, mock_valkey, test_user)

    # 削除予約
    await client.post(
        "/api/v1/auth/delete_account", json={"password": "password1234"}
    )
    await db.refresh(test_user.actor)

    # 間違ったパスワードでキャンセル
    resp = await client.post(
        "/api/v1/auth/cancel_deletion", json={"password": "wrongpassword"}
    )
    assert resp.status_code == 401


async def test_cancel_deletion_not_pending(db, app_client, mock_valkey, test_user):
    """削除予約されていないユーザーがキャンセルしようとすると 403。"""
    client = authed_client_for(app_client, mock_valkey, test_user)

    resp = await client.post(
        "/api/v1/auth/cancel_deletion", json={"password": "password1234"}
    )
    # get_deletion_pending_user が拒否する
    assert resp.status_code == 403
    assert "not pending deletion" in resp.json()["detail"]


# ── GET /api/v1/auth/deletion_status ─────────────────────────────────────


async def test_deletion_status_pending(db, app_client, mock_valkey, test_user):
    """削除予約中のステータスを取得できる。"""
    client = authed_client_for(app_client, mock_valkey, test_user)

    resp = await client.post(
        "/api/v1/auth/delete_account", json={"password": "password1234"}
    )
    assert resp.status_code == 200
    await db.refresh(test_user.actor)

    resp = await client.get("/api/v1/auth/deletion_status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["deletion_scheduled_at"] is not None


async def test_deletion_status_not_pending(db, app_client, mock_valkey, test_user):
    """削除予約されていないユーザーがステータスを取得しようとすると 403。"""
    client = authed_client_for(app_client, mock_valkey, test_user)

    resp = await client.get("/api/v1/auth/deletion_status")
    assert resp.status_code == 403


# ── POST /api/v1/admin/users/{user_id}/delete ────────────────────────────


async def test_admin_delete_user_success(db, app_client, mock_valkey):
    """管理者がユーザーを即時削除できる。"""
    from app.services.user_service import create_user

    admin = await make_admin_user(db)
    target = await create_user(
        db, "targetuser", "target@example.com", "password1234", display_name="Target"
    )
    client = authed_client_for(app_client, mock_valkey, admin)

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
        resp = await client.post(
            f"/api/v1/admin/users/{target.id}/delete",
            json={"reason": "規約違反"},
        )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    await db.refresh(target.actor)
    assert target.actor.is_deleted is True


async def test_admin_delete_self_forbidden(db, app_client, mock_valkey):
    """管理者は自分自身を削除できない。"""
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.post(
        f"/api/v1/admin/users/{admin.id}/delete",
        json={"reason": "テスト"},
    )
    assert resp.status_code == 422
    assert "Cannot delete self" in resp.json()["detail"]


async def test_admin_delete_system_account_forbidden(db, app_client, mock_valkey):
    """システムアカウントは削除できない。"""
    from app.services.user_service import create_user

    admin = await make_admin_user(db)
    system_user = await create_user(
        db, "systembot", "system@example.com", "password1234", display_name="System"
    )
    system_user.is_system = True
    await db.flush()

    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.post(
        f"/api/v1/admin/users/{system_user.id}/delete",
        json={"reason": "テスト"},
    )
    assert resp.status_code == 422
    assert "system account" in resp.json()["detail"]


async def test_admin_delete_nonexistent_user(db, app_client, mock_valkey):
    """存在しないユーザーの削除は 404。"""
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.post(
        f"/api/v1/admin/users/{uuid.uuid4()}/delete",
        json={"reason": "テスト"},
    )
    assert resp.status_code == 404


async def test_admin_delete_already_deleted(db, app_client, mock_valkey):
    """既に削除済みのユーザーは 422。"""
    from app.services.user_service import create_user

    admin = await make_admin_user(db)
    target = await create_user(
        db, "deleteduser", "deleted@example.com", "password1234", display_name="Deleted"
    )
    target.actor.deleted_at = datetime.now(timezone.utc)
    await db.flush()

    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.post(
        f"/api/v1/admin/users/{target.id}/delete",
        json={"reason": "テスト"},
    )
    assert resp.status_code == 422
    assert "Already deleted" in resp.json()["detail"]


async def test_admin_delete_regular_user_forbidden(db, app_client, mock_valkey, test_user):
    """一般ユーザーは管理者削除 API を使えない。"""
    from app.services.user_service import create_user

    target = await create_user(
        db, "targetuser2", "target2@example.com", "password1234", display_name="Target2"
    )
    client = authed_client_for(app_client, mock_valkey, test_user)

    resp = await client.post(
        f"/api/v1/admin/users/{target.id}/delete",
        json={"reason": "テスト"},
    )
    assert resp.status_code == 403


async def test_admin_delete_moderator_forbidden(db, app_client, mock_valkey):
    """モデレーターは管理者専用の削除 API を使えない。"""
    from app.services.user_service import create_user

    mod = await make_moderator_user(db)
    target = await create_user(
        db, "targetuser3", "target3@example.com", "password1234", display_name="Target3"
    )
    client = authed_client_for(app_client, mock_valkey, mod)

    resp = await client.post(
        f"/api/v1/admin/users/{target.id}/delete",
        json={"reason": "テスト"},
    )
    assert resp.status_code == 403
