"""Tests for admin API endpoints: domain blocks, queue, system stats, registrations."""

import uuid
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
async def admin_user(db):
    from app.services.user_service import create_user
    return await create_user(
        db, "adminuser", "admin@example.com", "password1234",
        display_name="Admin User", role="admin",
    )


@pytest.fixture
async def admin_client(app_client, admin_user, mock_valkey):
    mock_valkey.get = AsyncMock(return_value=str(admin_user.id))
    app_client.cookies.set("nekonoverse_session", "admin-session")
    return app_client


# --- Domain Blocks ---


async def test_list_domain_blocks_empty(admin_client):
    resp = await admin_client.get("/api/v1/admin/domain_blocks")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_domain_block(admin_client):
    resp = await admin_client.post("/api/v1/admin/domain_blocks", json={
        "domain": "spam.example",
        "severity": "suspend",
        "reason": "Spam domain",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["domain"] == "spam.example"
    assert data["severity"] == "suspend"


async def test_create_domain_block_duplicate(admin_client):
    await admin_client.post("/api/v1/admin/domain_blocks", json={
        "domain": "dup.example", "severity": "suspend",
    })
    resp = await admin_client.post("/api/v1/admin/domain_blocks", json={
        "domain": "dup.example", "severity": "suspend",
    })
    assert resp.status_code == 422


async def test_list_domain_blocks_after_create(admin_client):
    await admin_client.post("/api/v1/admin/domain_blocks", json={
        "domain": "listed.example", "severity": "silence",
    })
    resp = await admin_client.get("/api/v1/admin/domain_blocks")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert any(b["domain"] == "listed.example" for b in data)


async def test_delete_domain_block(admin_client):
    await admin_client.post("/api/v1/admin/domain_blocks", json={
        "domain": "removeme.example", "severity": "suspend",
    })
    resp = await admin_client.delete("/api/v1/admin/domain_blocks/removeme.example")
    assert resp.status_code == 200


async def test_delete_domain_block_not_found(admin_client):
    resp = await admin_client.delete("/api/v1/admin/domain_blocks/nonexistent.example")
    assert resp.status_code == 404


async def test_domain_blocks_unauthenticated(app_client, mock_valkey):
    resp = await app_client.get("/api/v1/admin/domain_blocks")
    assert resp.status_code in (401, 403)


# --- Queue Stats ---


async def test_queue_stats(admin_client, db):
    resp = await admin_client.get("/api/v1/admin/queue/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "pending" in data
    assert "delivered" in data
    assert "dead" in data


async def test_queue_jobs(admin_client, db):
    resp = await admin_client.get("/api/v1/admin/queue/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert "jobs" in data
    assert "total" in data


async def test_queue_retry_not_found(admin_client):
    fake_id = str(uuid.uuid4())
    resp = await admin_client.post(f"/api/v1/admin/queue/retry/{fake_id}")
    assert resp.status_code == 404


async def test_queue_retry_all(admin_client, db):
    resp = await admin_client.post("/api/v1/admin/queue/retry-all")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "retried" in data


# --- System Stats ---


async def test_system_stats(admin_client, mock_valkey):
    # info()メソッドの戻り値を明示的に設定
    mock_valkey.info = AsyncMock(return_value={
        "connected_clients": 1,
        "used_memory_human": "1M",
    })
    resp = await admin_client.get("/api/v1/admin/system/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "load_avg_1m" in data
    assert "memory_percent" in data
    assert "db_pool_size" in data


async def test_system_stats_unauthenticated(app_client, mock_valkey):
    resp = await app_client.get("/api/v1/admin/system/stats")
    assert resp.status_code in (401, 403)


# --- Pending Registrations ---


async def test_list_pending_registrations_empty(admin_client):
    resp = await admin_client.get("/api/v1/admin/registrations")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_pending_registrations(admin_client, db):
    from app.services.user_service import create_user
    await create_user(
        db, "pendinguser", "pending@example.com", "password1234",
        approval_status="pending", registration_reason="I want to join",
    )
    await db.commit()

    resp = await admin_client.get("/api/v1/admin/registrations")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["username"] == "pendinguser"


async def test_approve_registration(admin_client, db):
    from app.services.user_service import create_user
    pending_user = await create_user(
        db, "approveuser", "approve@example.com", "password1234",
        approval_status="pending",
    )
    await db.commit()

    resp = await admin_client.post(f"/api/v1/admin/registrations/{pending_user.id}/approve")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


async def test_approve_non_pending_user(admin_client, db):
    from app.services.user_service import create_user
    active_user = await create_user(
        db, "activeuser", "active@example.com", "password1234",
    )
    await db.commit()

    resp = await admin_client.post(f"/api/v1/admin/registrations/{active_user.id}/approve")
    assert resp.status_code == 422


async def test_reject_registration(admin_client, db):
    from app.services.user_service import create_user
    pending_user = await create_user(
        db, "rejectuser", "reject@example.com", "password1234",
        approval_status="pending",
    )
    await db.commit()

    resp = await admin_client.post(f"/api/v1/admin/registrations/{pending_user.id}/reject")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


async def test_reject_non_pending_user(admin_client, db):
    from app.services.user_service import create_user
    active_user = await create_user(
        db, "activeuser2", "active2@example.com", "password1234",
    )
    await db.commit()

    resp = await admin_client.post(f"/api/v1/admin/registrations/{active_user.id}/reject")
    assert resp.status_code == 422


# --- Remote Emoji ---


async def test_list_remote_emojis(admin_client):
    resp = await admin_client.get("/api/v1/admin/emoji/remote")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_list_remote_emoji_domains(admin_client):
    resp = await admin_client.get("/api/v1/admin/emoji/remote/domains")
    assert resp.status_code == 200
