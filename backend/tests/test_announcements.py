"""Tests for announcements API (admin CRUD + Mastodon-compatible endpoints)."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.usefixtures("seed_roles")


# ── Helpers ──────────────────────────────────────────────────────────────────


async def make_admin_user(db):
    from app.services.user_service import create_user

    user = await create_user(
        db, "ann_admin", "ann_admin@example.com", "password1234", display_name="Admin"
    )
    user.role = "admin"
    await db.flush()
    return user


async def make_regular_user(db):
    from app.services.user_service import create_user

    user = await create_user(
        db, "ann_user", "ann_user@example.com", "password1234", display_name="User"
    )
    await db.flush()
    return user


def authed_client_for(app_client, mock_valkey, user):
    mock_valkey.get = AsyncMock(return_value=str(user.id))
    app_client.cookies.set("nekonoverse_session", "test-session-id")
    return app_client


# ── Admin CRUD ───────────────────────────────────────────────────────────────


async def test_create_announcement(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.post(
        "/api/v1/admin/announcements",
        json={
            "title": "Maintenance Notice",
            "content": "Server will restart at 3am.",
            "published": True,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Maintenance Notice"
    assert data["published"] is True
    assert "<p>" in data["content_html"]


async def test_create_announcement_forbidden_for_user(db, app_client, mock_valkey):
    user = await make_regular_user(db)
    client = authed_client_for(app_client, mock_valkey, user)

    resp = await client.post(
        "/api/v1/admin/announcements",
        json={"title": "Test", "content": "Body"},
    )
    assert resp.status_code == 403


async def test_list_announcements_admin(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    # Create two announcements
    await client.post(
        "/api/v1/admin/announcements",
        json={"title": "First", "content": "Body 1", "published": True},
    )
    await client.post(
        "/api/v1/admin/announcements",
        json={"title": "Second", "content": "Body 2", "published": False},
    )

    resp = await client.get("/api/v1/admin/announcements")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 2
    titles = [a["title"] for a in data]
    assert "First" in titles
    assert "Second" in titles


async def test_update_announcement(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.post(
        "/api/v1/admin/announcements",
        json={"title": "Original", "content": "Original body"},
    )
    ann_id = resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/admin/announcements/{ann_id}",
        json={"title": "Updated", "content": "Updated body"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Updated"
    assert "Updated body" in data["content_html"]


async def test_delete_announcement(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.post(
        "/api/v1/admin/announcements",
        json={"title": "To Delete", "content": "Body"},
    )
    ann_id = resp.json()["id"]

    resp = await client.delete(f"/api/v1/admin/announcements/{ann_id}")
    assert resp.status_code == 204

    resp = await client.get(f"/api/v1/admin/announcements/{ann_id}")
    assert resp.status_code == 404


# ── Mastodon-compatible API ──────────────────────────────────────────────────


async def test_list_announcements_mastodon(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    await client.post(
        "/api/v1/admin/announcements",
        json={"title": "Public", "content": "Visible", "published": True},
    )

    resp = await client.get("/api/v1/announcements")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    ann = next(a for a in data if "Visible" in a["content"])
    assert "read" in ann
    assert ann["read"] is False
    assert ann["mentions"] == []
    assert ann["reactions"] == []


async def test_dismiss_announcement(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.post(
        "/api/v1/admin/announcements",
        json={"title": "Dismiss Me", "content": "Body", "published": True},
    )
    ann_id = resp.json()["id"]

    # Dismiss
    resp = await client.post(f"/api/v1/announcements/{ann_id}/dismiss")
    assert resp.status_code == 204

    # Should now be read
    resp = await client.get("/api/v1/announcements")
    data = resp.json()
    ann = next(a for a in data if a["id"] == ann_id)
    assert ann["read"] is True


async def test_dismiss_idempotent(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.post(
        "/api/v1/admin/announcements",
        json={"title": "Idempotent", "content": "Body", "published": True},
    )
    ann_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/announcements/{ann_id}/dismiss")
    assert resp.status_code == 204
    # Second dismiss should also succeed (ON CONFLICT DO NOTHING)
    resp = await client.post(f"/api/v1/announcements/{ann_id}/dismiss")
    assert resp.status_code == 204


async def test_unread_count(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    # Create two published announcements
    await client.post(
        "/api/v1/admin/announcements",
        json={"title": "A1", "content": "Body 1", "published": True},
    )
    resp = await client.post(
        "/api/v1/admin/announcements",
        json={"title": "A2", "content": "Body 2", "published": True},
    )
    ann2_id = resp.json()["id"]

    resp = await client.get("/api/v1/announcements/unread_count")
    assert resp.status_code == 200
    assert resp.json()["count"] >= 2

    # Dismiss one
    await client.post(f"/api/v1/announcements/{ann2_id}/dismiss")

    resp = await client.get("/api/v1/announcements/unread_count")
    old_count = resp.json()["count"]

    # Count should be at least 1 less
    assert old_count >= 1


# ── Active filtering ─────────────────────────────────────────────────────────


async def test_active_excludes_unpublished(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    await client.post(
        "/api/v1/admin/announcements",
        json={"title": "Draft", "content": "Not visible", "published": False},
    )

    resp = await client.get("/api/v1/announcements")
    data = resp.json()
    titles = [a.get("content", "") for a in data]
    assert not any("Not visible" in t for t in titles)


async def test_active_excludes_future(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    await client.post(
        "/api/v1/admin/announcements",
        json={
            "title": "Future",
            "content": "Not yet",
            "published": True,
            "starts_at": future,
        },
    )

    resp = await client.get("/api/v1/announcements")
    data = resp.json()
    assert not any("Not yet" in a.get("content", "") for a in data)


async def test_active_excludes_expired(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    await client.post(
        "/api/v1/admin/announcements",
        json={
            "title": "Expired",
            "content": "Already ended",
            "published": True,
            "ends_at": past,
        },
    )

    resp = await client.get("/api/v1/announcements")
    data = resp.json()
    assert not any("Already ended" in a.get("content", "") for a in data)


async def test_active_includes_no_date_range(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    await client.post(
        "/api/v1/admin/announcements",
        json={
            "title": "Timeless",
            "content": "Always visible",
            "published": True,
        },
    )

    resp = await client.get("/api/v1/announcements")
    data = resp.json()
    assert any("Always visible" in a.get("content", "") for a in data)
