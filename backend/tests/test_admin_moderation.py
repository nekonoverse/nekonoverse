"""Tests for admin and moderation API endpoints (Phase 3)."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from tests.conftest import make_note, make_remote_actor


# ── Helpers ──────────────────────────────────────────────────────────────────


async def make_admin_user(db):
    """Create a user with admin role."""
    from app.services.user_service import create_user
    user = await create_user(db, "adminuser", "admin@example.com", "password1234",
                             display_name="Admin")
    user.role = "admin"
    await db.flush()
    return user


async def make_moderator_user(db):
    """Create a user with moderator role."""
    from app.services.user_service import create_user
    user = await create_user(db, "moduser", "mod@example.com", "password1234",
                             display_name="Moderator")
    user.role = "moderator"
    await db.flush()
    return user


def authed_client_for(app_client, mock_valkey, user):
    """Set up app_client cookies for a specific user."""
    mock_valkey.get = AsyncMock(return_value=str(user.id))
    app_client.cookies.set("nekonoverse_session", "test-session-id")
    return app_client


# ── Server Settings ─────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_server_settings_admin(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.get("/api/v1/admin/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "server_name" in data
    assert "registration_open" in data


@pytest.mark.anyio
async def test_get_server_settings_forbidden_for_regular_user(db, app_client, mock_valkey, test_user):
    client = authed_client_for(app_client, mock_valkey, test_user)
    resp = await client.get("/api/v1/admin/settings")
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_update_server_settings(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.patch("/api/v1/admin/settings", json={
        "server_name": "Test Instance",
        "server_description": "A test server",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["server_name"] == "Test Instance"
    assert data["server_description"] == "A test server"


@pytest.mark.anyio
async def test_update_server_settings_forbidden_moderator(db, app_client, mock_valkey):
    mod = await make_moderator_user(db)
    client = authed_client_for(app_client, mock_valkey, mod)

    resp = await client.patch("/api/v1/admin/settings", json={"server_name": "X"})
    assert resp.status_code == 403


# ── Stats ────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
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


@pytest.mark.anyio
async def test_admin_stats_moderator_allowed(db, app_client, mock_valkey):
    mod = await make_moderator_user(db)
    client = authed_client_for(app_client, mock_valkey, mod)

    resp = await client.get("/api/v1/admin/stats")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_admin_stats_forbidden_regular_user(db, app_client, mock_valkey, test_user):
    client = authed_client_for(app_client, mock_valkey, test_user)
    resp = await client.get("/api/v1/admin/stats")
    assert resp.status_code == 403


# ── User Management ─────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_list_users(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.get("/api/v1/admin/users")
    assert resp.status_code == 200
    users = resp.json()
    assert len(users) >= 2  # admin + test_user
    assert all("username" in u for u in users)
    assert all("role" in u for u in users)


@pytest.mark.anyio
async def test_change_user_role(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.patch(f"/api/v1/admin/users/{test_user.id}/role",
                              json={"role": "moderator"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "moderator"


@pytest.mark.anyio
async def test_change_own_role_forbidden(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.patch(f"/api/v1/admin/users/{admin.id}/role",
                              json={"role": "user"})
    assert resp.status_code == 422
    assert "own role" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_change_role_moderator_forbidden(db, app_client, mock_valkey, test_user):
    mod = await make_moderator_user(db)
    client = authed_client_for(app_client, mock_valkey, mod)

    resp = await client.patch(f"/api/v1/admin/users/{test_user.id}/role",
                              json={"role": "admin"})
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_invalid_role_rejected(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.patch(f"/api/v1/admin/users/{test_user.id}/role",
                              json={"role": "superadmin"})
    assert resp.status_code == 422


# ── Suspend / Unsuspend ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_suspend_user(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.post(f"/api/v1/admin/users/{test_user.id}/suspend",
                             json={"reason": "spam"})
    assert resp.status_code == 200

    await db.refresh(test_user.actor)
    assert test_user.actor.is_suspended


@pytest.mark.anyio
async def test_suspend_already_suspended(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    # First suspend
    await client.post(f"/api/v1/admin/users/{test_user.id}/suspend")
    # Second suspend should fail
    resp = await client.post(f"/api/v1/admin/users/{test_user.id}/suspend")
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_suspend_self_forbidden(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.post(f"/api/v1/admin/users/{admin.id}/suspend")
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_unsuspend_user(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    # Suspend then unsuspend
    await client.post(f"/api/v1/admin/users/{test_user.id}/suspend")
    resp = await client.post(f"/api/v1/admin/users/{test_user.id}/unsuspend")
    assert resp.status_code == 200

    await db.refresh(test_user.actor)
    assert not test_user.actor.is_suspended


@pytest.mark.anyio
async def test_unsuspend_not_suspended(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.post(f"/api/v1/admin/users/{test_user.id}/unsuspend")
    assert resp.status_code == 422


# ── Silence / Unsilence ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_silence_user(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.post(f"/api/v1/admin/users/{test_user.id}/silence",
                             json={"reason": "harassment"})
    assert resp.status_code == 200

    await db.refresh(test_user.actor)
    assert test_user.actor.is_silenced


@pytest.mark.anyio
async def test_silence_already_silenced(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    await client.post(f"/api/v1/admin/users/{test_user.id}/silence")
    resp = await client.post(f"/api/v1/admin/users/{test_user.id}/silence")
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_unsilence_user(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    await client.post(f"/api/v1/admin/users/{test_user.id}/silence")
    resp = await client.post(f"/api/v1/admin/users/{test_user.id}/unsilence")
    assert resp.status_code == 200

    await db.refresh(test_user.actor)
    assert not test_user.actor.is_silenced


# ── Reports ──────────────────────────────────────────────────────────────────


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
async def test_resolve_report(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    from app.services.report_service import create_report
    report = await create_report(db, admin.actor, test_user.actor, comment="test")
    await db.commit()

    resp = await client.post(f"/api/v1/admin/reports/{report.id}/resolve")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_reject_report(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    from app.services.report_service import create_report
    report = await create_report(db, admin.actor, test_user.actor, comment="test")
    await db.commit()

    resp = await client.post(f"/api/v1/admin/reports/{report.id}/reject")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_resolve_already_resolved_report(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    from app.services.report_service import create_report
    report = await create_report(db, admin.actor, test_user.actor, comment="test")
    await db.commit()

    await client.post(f"/api/v1/admin/reports/{report.id}/resolve")
    resp = await client.post(f"/api/v1/admin/reports/{report.id}/resolve")
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_resolve_nonexistent_report(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.post(f"/api/v1/admin/reports/{uuid.uuid4()}/resolve")
    assert resp.status_code == 404


# ── Post Moderation ──────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_admin_delete_note(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    note = await make_note(db, test_user.actor, content="bad post")

    resp = await client.request("DELETE", f"/api/v1/admin/notes/{note.id}",
                                json={"reason": "TOS violation"})
    assert resp.status_code == 200

    # Note should be soft-deleted
    await db.refresh(note)
    assert note.deleted_at is not None


@pytest.mark.anyio
async def test_admin_delete_nonexistent_note(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.delete(f"/api/v1/admin/notes/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
async def test_moderation_log_forbidden_regular_user(db, app_client, mock_valkey, test_user):
    client = authed_client_for(app_client, mock_valkey, test_user)
    resp = await client.get("/api/v1/admin/log")
    assert resp.status_code == 403


# ── Unauthenticated access ──────────────────────────────────────────────────


@pytest.mark.anyio
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
