"""Tests for admin and moderation API endpoints (Phase 3)."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from tests.conftest import make_note, make_remote_actor

pytestmark = pytest.mark.usefixtures("seed_roles")


# ── Helpers ──────────────────────────────────────────────────────────────────


async def make_admin_user(db):
    """Create a user with admin role."""
    from app.services.user_service import create_user

    user = await create_user(
        db, "adminuser", "admin@example.com", "password1234", display_name="Admin"
    )
    user.role = "admin"
    await db.flush()
    return user


async def make_moderator_user(db):
    """Create a user with moderator role."""
    from app.services.user_service import create_user

    user = await create_user(
        db, "moduser", "mod@example.com", "password1234", display_name="Moderator"
    )
    user.role = "moderator"
    await db.flush()
    return user


def authed_client_for(app_client, mock_valkey, user):
    """Set up app_client cookies for a specific user."""
    mock_valkey.get = AsyncMock(return_value=str(user.id))
    app_client.cookies.set("nekonoverse_session", "test-session-id")
    return app_client


# ── Server Settings ─────────────────────────────────────────────────────────



async def test_get_server_settings_admin(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.get("/api/v1/admin/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "server_name" in data
    assert "registration_open" in data



async def test_get_server_settings_forbidden_for_regular_user(
    db, app_client, mock_valkey, test_user
):
    client = authed_client_for(app_client, mock_valkey, test_user)
    resp = await client.get("/api/v1/admin/settings")
    assert resp.status_code == 403



async def test_update_server_settings(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.patch(
        "/api/v1/admin/settings",
        json={
            "server_name": "Test Instance",
            "server_description": "A test server",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["server_name"] == "Test Instance"
    assert data["server_description"] == "A test server"



async def test_update_server_settings_forbidden_moderator(db, app_client, mock_valkey):
    mod = await make_moderator_user(db)
    client = authed_client_for(app_client, mock_valkey, mod)

    resp = await client.patch("/api/v1/admin/settings", json={"server_name": "X"})
    assert resp.status_code == 403


# ── Stats ────────────────────────────────────────────────────────────────────



async def test_admin_stats(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.get("/api/v1/admin/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "user_count" in data
    assert "note_count" in data
    assert "domain_count" in data
    assert data["user_count"] >= 1  # at least the admin user



async def test_admin_stats_note_count_local_only(db, app_client, mock_valkey):
    """note_count should only include local notes, not remote ones."""
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    local_actor = admin.actor
    remote_actor = await make_remote_actor(db, username="stats_remote", domain="stats.example")

    await make_note(db, local_actor, content="local note 1", local=True)
    await make_note(db, local_actor, content="local note 2", local=True)
    await make_note(db, remote_actor, content="remote note", local=False)
    await db.commit()

    resp = await client.get("/api/v1/admin/stats")
    assert resp.status_code == 200
    data = resp.json()
    # リモート投稿を含めず、ローカル投稿のみカウントされること
    assert data["note_count"] == 2



async def test_admin_stats_domain_count_active_only(db, app_client, mock_valkey):
    """domain_count should only include domains with active delivery or follow relationships."""
    from app.models.delivery import DeliveryJob
    from app.models.follow import Follow

    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)
    local_actor = admin.actor

    # アクティブな配送先ドメイン
    active_remote = await make_remote_actor(
        db, username="active_r", domain="active-delivery.example"
    )
    db.add(
        DeliveryJob(
            actor_id=local_actor.id,
            target_inbox_url=f"https://{active_remote.domain}/inbox",
            payload={"type": "Create"},
            status="delivered",
        )
    )

    # フォロー関係のあるリモートドメイン（ローカル→リモート）
    following_remote = await make_remote_actor(
        db, username="following_r", domain="following.example"
    )
    db.add(
        Follow(
            follower_id=local_actor.id,
            following_id=following_remote.id,
            accepted=True,
        )
    )

    # フォロー関係のあるリモートドメイン（リモート→ローカル）
    follower_remote = await make_remote_actor(db, username="follower_r", domain="follower.example")
    db.add(
        Follow(
            follower_id=follower_remote.id,
            following_id=local_actor.id,
            accepted=True,
        )
    )

    # 非アクティブなドメイン（deadステータスのみ、フォロー関係なし）
    inactive_remote = await make_remote_actor(db, username="inactive_r", domain="inactive.example")
    db.add(
        DeliveryJob(
            actor_id=local_actor.id,
            target_inbox_url=f"https://{inactive_remote.domain}/inbox",
            payload={"type": "Create"},
            status="dead",
        )
    )

    await db.commit()

    resp = await client.get("/api/v1/admin/stats")
    assert resp.status_code == 200
    data = resp.json()
    # active-delivery.example, following.example, follower.exampleの3ドメインのみ
    assert data["domain_count"] == 3



async def test_admin_stats_moderator_allowed(db, app_client, mock_valkey):
    mod = await make_moderator_user(db)
    client = authed_client_for(app_client, mock_valkey, mod)

    resp = await client.get("/api/v1/admin/stats")
    assert resp.status_code == 200



async def test_admin_stats_forbidden_regular_user(db, app_client, mock_valkey, test_user):
    client = authed_client_for(app_client, mock_valkey, test_user)
    resp = await client.get("/api/v1/admin/stats")
    assert resp.status_code == 403


# ── User Management ─────────────────────────────────────────────────────────



async def test_list_users(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.get("/api/v1/admin/users")
    assert resp.status_code == 200
    users = resp.json()
    assert len(users) >= 2  # admin + test_user
    assert all("username" in u for u in users)
    assert all("role" in u for u in users)



async def test_change_user_role(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.patch(
        f"/api/v1/admin/users/{test_user.id}/role", json={"role": "moderator"}
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "moderator"



async def test_change_own_role_forbidden(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.patch(f"/api/v1/admin/users/{admin.id}/role", json={"role": "user"})
    assert resp.status_code == 422
    assert "own role" in resp.json()["detail"].lower()



async def test_change_role_moderator_forbidden(db, app_client, mock_valkey, test_user):
    mod = await make_moderator_user(db)
    client = authed_client_for(app_client, mock_valkey, mod)

    resp = await client.patch(f"/api/v1/admin/users/{test_user.id}/role", json={"role": "admin"})
    assert resp.status_code == 403



async def test_invalid_role_rejected(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.patch(
        f"/api/v1/admin/users/{test_user.id}/role", json={"role": "superadmin"}
    )
    assert resp.status_code == 422


# ── Suspend / Unsuspend ──────────────────────────────────────────────────────



async def test_suspend_user(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.post(f"/api/v1/admin/users/{test_user.id}/suspend", json={"reason": "spam"})
    assert resp.status_code == 200

    await db.refresh(test_user.actor)
    assert test_user.actor.is_suspended



async def test_suspend_already_suspended(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    # First suspend
    await client.post(f"/api/v1/admin/users/{test_user.id}/suspend")
    # Second suspend should fail
    resp = await client.post(f"/api/v1/admin/users/{test_user.id}/suspend")
    assert resp.status_code == 422



async def test_suspend_self_forbidden(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.post(f"/api/v1/admin/users/{admin.id}/suspend")
    assert resp.status_code == 422



async def test_unsuspend_user(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    # Suspend then unsuspend
    await client.post(f"/api/v1/admin/users/{test_user.id}/suspend")
    resp = await client.post(f"/api/v1/admin/users/{test_user.id}/unsuspend")
    assert resp.status_code == 200

    await db.refresh(test_user.actor)
    assert not test_user.actor.is_suspended



async def test_unsuspend_not_suspended(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.post(f"/api/v1/admin/users/{test_user.id}/unsuspend")
    assert resp.status_code == 422


# ── Silence / Unsilence ──────────────────────────────────────────────────────



async def test_silence_user(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.post(
        f"/api/v1/admin/users/{test_user.id}/silence", json={"reason": "harassment"}
    )
    assert resp.status_code == 200

    await db.refresh(test_user.actor)
    assert test_user.actor.is_silenced



async def test_silence_already_silenced(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    await client.post(f"/api/v1/admin/users/{test_user.id}/silence")
    resp = await client.post(f"/api/v1/admin/users/{test_user.id}/silence")
    assert resp.status_code == 422



async def test_unsilence_user(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    await client.post(f"/api/v1/admin/users/{test_user.id}/silence")
    resp = await client.post(f"/api/v1/admin/users/{test_user.id}/unsilence")
    assert resp.status_code == 200

    await db.refresh(test_user.actor)
    assert not test_user.actor.is_silenced


# ── Reports ──────────────────────────────────────────────────────────────────



async def test_create_and_list_reports(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    # Create a report via service
    from app.services.report_service import create_report

    await create_report(db, admin.actor, test_user.actor, comment="spammer")
    await db.commit()

    resp = await client.get("/api/v1/admin/reports")
    assert resp.status_code == 200
    reports = resp.json()
    assert len(reports) >= 1
    assert reports[0]["status"] == "open"
    assert reports[0]["comment"] == "spammer"



async def test_list_reports_filter_status(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    from app.services.report_service import create_report

    await create_report(db, admin.actor, test_user.actor, comment="test")
    await db.commit()

    resp = await client.get("/api/v1/admin/reports?status=resolved")
    assert resp.status_code == 200
    # No resolved reports yet
    assert len(resp.json()) == 0



async def test_resolve_report(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    from app.services.report_service import create_report

    report = await create_report(db, admin.actor, test_user.actor, comment="test")
    await db.commit()

    resp = await client.post(f"/api/v1/admin/reports/{report.id}/resolve")
    assert resp.status_code == 200



async def test_reject_report(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    from app.services.report_service import create_report

    report = await create_report(db, admin.actor, test_user.actor, comment="test")
    await db.commit()

    resp = await client.post(f"/api/v1/admin/reports/{report.id}/reject")
    assert resp.status_code == 200



async def test_resolve_already_resolved_report(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    from app.services.report_service import create_report

    report = await create_report(db, admin.actor, test_user.actor, comment="test")
    await db.commit()

    await client.post(f"/api/v1/admin/reports/{report.id}/resolve")
    resp = await client.post(f"/api/v1/admin/reports/{report.id}/resolve")
    assert resp.status_code == 422



async def test_resolve_nonexistent_report(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.post(f"/api/v1/admin/reports/{uuid.uuid4()}/resolve")
    assert resp.status_code == 404


# ── Post Moderation ──────────────────────────────────────────────────────────



async def test_admin_delete_note(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    note = await make_note(db, test_user.actor, content="bad post")

    resp = await client.request(
        "DELETE", f"/api/v1/admin/notes/{note.id}", json={"reason": "TOS violation"}
    )
    assert resp.status_code == 200

    # Note should be soft-deleted
    await db.refresh(note)
    assert note.deleted_at is not None



async def test_admin_delete_nonexistent_note(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.delete(f"/api/v1/admin/notes/{uuid.uuid4()}")
    assert resp.status_code == 404



async def test_force_sensitive(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    note = await make_note(db, test_user.actor, content="nsfw content")
    assert not note.sensitive

    resp = await client.post(f"/api/v1/admin/notes/{note.id}/sensitive")
    assert resp.status_code == 200

    await db.refresh(note)
    assert note.sensitive


# ── Moderation Log ───────────────────────────────────────────────────────────



async def test_moderation_log(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    # Perform an action that creates a log entry
    await client.post(f"/api/v1/admin/users/{test_user.id}/silence")

    resp = await client.get("/api/v1/admin/log")
    assert resp.status_code == 200
    log = resp.json()
    assert len(log) >= 1
    assert any(e["action"] == "silence" for e in log)



async def test_moderation_log_forbidden_regular_user(db, app_client, mock_valkey, test_user):
    client = authed_client_for(app_client, mock_valkey, test_user)
    resp = await client.get("/api/v1/admin/log")
    assert resp.status_code == 403


# ── Role Hierarchy ──────────────────────────────────────────────────────────



async def test_moderator_cannot_suspend_admin(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    mod = await make_moderator_user(db)
    client = authed_client_for(app_client, mock_valkey, mod)

    resp = await client.post(f"/api/v1/admin/users/{admin.id}/suspend")
    assert resp.status_code == 403
    assert "staff" in resp.json()["detail"].lower()



async def test_moderator_cannot_silence_admin(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    mod = await make_moderator_user(db)
    client = authed_client_for(app_client, mock_valkey, mod)

    resp = await client.post(f"/api/v1/admin/users/{admin.id}/silence")
    assert resp.status_code == 403



async def test_moderator_cannot_suspend_moderator(db, app_client, mock_valkey):
    mod1 = await make_moderator_user(db)

    from app.services.user_service import create_user

    mod2 = await create_user(
        db, "moduser2", "mod2@example.com", "password1234", display_name="Mod2"
    )
    mod2.role = "moderator"
    await db.flush()

    client = authed_client_for(app_client, mock_valkey, mod1)
    resp = await client.post(f"/api/v1/admin/users/{mod2.id}/suspend")
    assert resp.status_code == 403



async def test_admin_can_suspend_moderator(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    mod = await make_moderator_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.post(f"/api/v1/admin/users/{mod.id}/suspend")
    assert resp.status_code == 200



async def test_moderator_cannot_delete_admin_note(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    mod = await make_moderator_user(db)

    note = await make_note(db, admin.actor, content="admin post")
    client = authed_client_for(app_client, mock_valkey, mod)

    resp = await client.request("DELETE", f"/api/v1/admin/notes/{note.id}")
    assert resp.status_code == 403



async def test_moderator_cannot_force_sensitive_admin_note(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    mod = await make_moderator_user(db)

    note = await make_note(db, admin.actor, content="admin post")
    client = authed_client_for(app_client, mock_valkey, mod)

    resp = await client.post(f"/api/v1/admin/notes/{note.id}/sensitive")
    assert resp.status_code == 403



async def test_moderator_can_suspend_regular_user(db, app_client, mock_valkey, test_user):
    mod = await make_moderator_user(db)
    client = authed_client_for(app_client, mock_valkey, mod)

    resp = await client.post(f"/api/v1/admin/users/{test_user.id}/suspend")
    assert resp.status_code == 200



async def test_moderator_can_delete_regular_user_note(db, app_client, mock_valkey, test_user):
    mod = await make_moderator_user(db)
    note = await make_note(db, test_user.actor, content="regular post")
    client = authed_client_for(app_client, mock_valkey, mod)

    resp = await client.request("DELETE", f"/api/v1/admin/notes/{note.id}")
    assert resp.status_code == 200


# ── Unauthenticated access ──────────────────────────────────────────────────



async def test_admin_endpoints_require_auth(app_client):
    endpoints = [
        ("GET", "/api/v1/admin/settings"),
        ("GET", "/api/v1/admin/stats"),
        ("GET", "/api/v1/admin/users"),
        ("GET", "/api/v1/admin/domain_blocks"),
        ("GET", "/api/v1/admin/reports"),
        ("GET", "/api/v1/admin/log"),
    ]
    for method, url in endpoints:
        resp = await app_client.request(method, url)
        assert resp.status_code == 401, f"{method} {url} should require auth"


# ── Suspended user session invalidation ──────────────────────────────────────



async def test_suspend_user_invalidates_sessions(db, app_client, mock_valkey, test_user):
    """Suspending a user should call valkey.scan to find and delete their sessions."""
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    # Mock scan to return a session key for the target user
    target_session_key = "session:abc123"
    mock_valkey.scan = AsyncMock(return_value=(0, [target_session_key]))
    # When get is called for the session key, return the target user's id
    original_get = mock_valkey.get

    async def get_side_effect(key):
        if key == target_session_key:
            return str(test_user.id)
        # For admin's session lookup, delegate to original
        return await original_get(key)

    mock_valkey.get = AsyncMock(side_effect=get_side_effect)

    resp = await client.post(f"/api/v1/admin/users/{test_user.id}/suspend", json={"reason": "spam"})
    assert resp.status_code == 200

    # Verify scan was called with session:* pattern
    mock_valkey.scan.assert_called()
    # Verify the target user's session was deleted
    mock_valkey.delete.assert_any_call(target_session_key)



async def test_suspended_user_gets_403(db, app_client, mock_valkey, test_user):
    """A suspended user should get 403 when trying to access authenticated endpoints."""
    admin = await make_admin_user(db)

    # First: suspend the user (as admin)
    admin_client = authed_client_for(app_client, mock_valkey, admin)
    # Need scan mock for the suspension
    mock_valkey.scan = AsyncMock(return_value=(0, []))

    resp = await admin_client.post(f"/api/v1/admin/users/{test_user.id}/suspend")
    assert resp.status_code == 200

    # Now: try to access an endpoint as the suspended user
    suspended_client = authed_client_for(app_client, mock_valkey, test_user)

    resp = await suspended_client.get("/api/v1/accounts/verify_credentials")
    assert resp.status_code == 403
    assert "suspended" in resp.json()["detail"].lower()
