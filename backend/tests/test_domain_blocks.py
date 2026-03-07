"""Tests for domain blocks, federation filtering, and silence/suspend integration."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from tests.conftest import make_note, make_remote_actor


# ── Helpers ──────────────────────────────────────────────────────────────────


async def make_admin_user(db):
    from app.services.user_service import create_user
    user = await create_user(db, f"admin_{uuid.uuid4().hex[:8]}", f"admin_{uuid.uuid4().hex[:8]}@example.com",
                             "password1234", display_name="Admin")
    user.role = "admin"
    await db.flush()
    return user


def authed_client_for(app_client, mock_valkey, user):
    mock_valkey.get = AsyncMock(return_value=str(user.id))
    app_client.cookies.set("nekonoverse_session", "test-session-id")
    return app_client


# ── Domain Block CRUD API ────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_create_domain_block(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.post("/api/v1/admin/domain_blocks", json={
        "domain": "evil.example.com",
        "severity": "suspend",
        "reason": "spam server",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["domain"] == "evil.example.com"
    assert data["severity"] == "suspend"
    assert data["reason"] == "spam server"


@pytest.mark.anyio
async def test_list_domain_blocks(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    # Create a block first
    await client.post("/api/v1/admin/domain_blocks", json={
        "domain": "blocked1.example",
    })

    resp = await client.get("/api/v1/admin/domain_blocks")
    assert resp.status_code == 200
    blocks = resp.json()
    assert any(b["domain"] == "blocked1.example" for b in blocks)


@pytest.mark.anyio
async def test_remove_domain_block(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    await client.post("/api/v1/admin/domain_blocks", json={
        "domain": "removeme.example",
    })

    resp = await client.delete("/api/v1/admin/domain_blocks/removeme.example")
    assert resp.status_code == 200

    # Verify it's gone
    resp = await client.get("/api/v1/admin/domain_blocks")
    domains = [b["domain"] for b in resp.json()]
    assert "removeme.example" not in domains


@pytest.mark.anyio
async def test_remove_nonexistent_domain_block(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.delete("/api/v1/admin/domain_blocks/nope.example")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_duplicate_domain_block(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    await client.post("/api/v1/admin/domain_blocks", json={
        "domain": "dup.example",
    })
    resp = await client.post("/api/v1/admin/domain_blocks", json={
        "domain": "dup.example",
    })
    assert resp.status_code == 422


# ── Domain Block Service ─────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_is_domain_blocked_service(db, mock_valkey):
    admin = await make_admin_user(db)
    from app.services.domain_block_service import create_domain_block, is_domain_blocked

    await create_domain_block(db, "blocked.test", "suspend", "test", admin)
    await db.commit()

    assert await is_domain_blocked(db, "blocked.test")
    assert not await is_domain_blocked(db, "safe.test")


@pytest.mark.anyio
async def test_is_domain_blocked_empty_domain(db, mock_valkey):
    from app.services.domain_block_service import is_domain_blocked

    assert not await is_domain_blocked(db, "")
    assert not await is_domain_blocked(db, None)


# ── Inbox Domain Block Filter ───────────────────────────────────────────────


@pytest.mark.anyio
async def test_inbox_rejects_blocked_domain(db, mock_valkey):
    """process_inbox_activity should silently drop activities from blocked domains."""
    admin = await make_admin_user(db)
    from app.services.domain_block_service import create_domain_block

    await create_domain_block(db, "bad.example", "suspend", None, admin)
    await db.commit()

    from app.activitypub.routes import process_inbox_activity

    activity = {
        "id": f"https://bad.example/activity/{uuid.uuid4()}",
        "type": "Create",
        "actor": "https://bad.example/users/baduser",
        "object": {"type": "Note", "content": "spam"},
    }

    # Should not raise — just silently skip
    await process_inbox_activity(db, activity)


@pytest.mark.anyio
async def test_inbox_allows_non_blocked_domain(db, mock_valkey):
    """Activities from non-blocked domains should not be rejected at domain check."""
    from app.activitypub.routes import process_inbox_activity

    activity = {
        "id": f"https://good.example/activity/{uuid.uuid4()}",
        "type": "UnknownType",  # Will be unhandled but not domain-blocked
        "actor": "https://good.example/users/gooduser",
    }

    # Should process without error (unhandled type just logs)
    await process_inbox_activity(db, activity)


# ── Delivery Domain Block Filter ─────────────────────────────────────────────


@pytest.mark.anyio
async def test_delivery_skips_blocked_domain(db, mock_valkey):
    """enqueue_delivery should return None for blocked domains."""
    admin = await make_admin_user(db)
    from app.services.domain_block_service import create_domain_block

    await create_domain_block(db, "blocked-delivery.example", "suspend", None, admin)
    await db.commit()

    from app.services.delivery_service import enqueue_delivery

    result = await enqueue_delivery(
        db, admin.actor_id,
        "https://blocked-delivery.example/inbox",
        {"type": "Create"},
    )
    assert result is None


@pytest.mark.anyio
async def test_delivery_allows_non_blocked_domain(db, mock_valkey):
    """enqueue_delivery should succeed for non-blocked domains."""
    admin = await make_admin_user(db)

    from app.services.delivery_service import enqueue_delivery

    result = await enqueue_delivery(
        db, admin.actor_id,
        "https://safe-delivery.example/inbox",
        {"type": "Create"},
    )
    assert result is not None
    assert result.status == "pending"


# ── Suspended Actor 410 Gone ─────────────────────────────────────────────────


@pytest.mark.anyio
async def test_suspended_actor_returns_410(db, app_client, mock_valkey, test_user):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    # Suspend the test user
    await client.post(f"/api/v1/admin/users/{test_user.id}/suspend")

    # Try to fetch the suspended actor via AP endpoint
    resp = await app_client.get(
        f"/users/{test_user.actor.username}",
        headers={"Accept": "application/activity+json"},
    )
    assert resp.status_code == 410


@pytest.mark.anyio
async def test_non_suspended_actor_returns_200(db, app_client, mock_valkey, test_user):
    resp = await app_client.get(
        f"/users/{test_user.actor.username}",
        headers={"Accept": "application/activity+json"},
    )
    assert resp.status_code == 200


# ── Silence Filter on Public Timeline ────────────────────────────────────────


@pytest.mark.anyio
async def test_silenced_user_excluded_from_public_timeline(db, mock_valkey, test_user, test_user_b):
    """Silenced user's notes should not appear in public timeline."""
    # Create notes for both users
    note_a = await make_note(db, test_user.actor, content="Normal post")
    note_b = await make_note(db, test_user_b.actor, content="Silenced post")

    # Silence user B
    from app.services.moderation_service import silence_actor
    admin = await make_admin_user(db)
    await silence_actor(db, test_user_b.actor, admin, "test")
    await db.commit()

    from app.services.note_service import get_public_timeline
    notes = await get_public_timeline(db, limit=50)

    note_ids = [n.id for n in notes]
    assert note_a.id in note_ids, "Normal user's note should appear"
    assert note_b.id not in note_ids, "Silenced user's note should be excluded"


@pytest.mark.anyio
async def test_unsilenced_user_reappears_in_public_timeline(db, mock_valkey, test_user):
    """After unsilencing, user's notes should appear in public timeline again."""
    note = await make_note(db, test_user.actor, content="Test post")

    admin = await make_admin_user(db)
    from app.services.moderation_service import silence_actor, unsilence_actor

    await silence_actor(db, test_user.actor, admin, "test")
    await db.commit()

    from app.services.note_service import get_public_timeline
    notes = await get_public_timeline(db, limit=50)
    assert note.id not in [n.id for n in notes]

    await unsilence_actor(db, test_user.actor, admin)
    await db.commit()

    notes = await get_public_timeline(db, limit=50)
    assert note.id in [n.id for n in notes]


# ── Suspend Soft-deletes Notes ───────────────────────────────────────────────


@pytest.mark.anyio
async def test_suspend_soft_deletes_notes(db, mock_valkey, test_user):
    """Suspending an actor should soft-delete all their notes."""
    note1 = await make_note(db, test_user.actor, content="Post 1")
    note2 = await make_note(db, test_user.actor, content="Post 2")
    await db.commit()

    admin = await make_admin_user(db)
    from app.services.moderation_service import suspend_actor

    await suspend_actor(db, test_user.actor, admin, "ban")
    await db.commit()

    await db.refresh(note1)
    await db.refresh(note2)
    assert note1.deleted_at is not None
    assert note2.deleted_at is not None


# ── Flag Handler ─────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_flag_handler_creates_report(db, mock_valkey, test_user):
    """Incoming Flag activity should create a Report."""
    remote = await make_remote_actor(db, username="reporter", domain="other.example")

    from app.activitypub.handlers.flag import handle_flag

    activity = {
        "id": f"https://other.example/flags/{uuid.uuid4()}",
        "type": "Flag",
        "actor": remote.ap_id,
        "object": [test_user.actor.ap_id],
        "content": "This user is spamming",
    }

    await handle_flag(db, activity)

    from app.services.report_service import list_reports
    reports = await list_reports(db)
    assert len(reports) >= 1
    assert reports[0].comment == "This user is spamming"
    assert reports[0].reporter_actor_id == remote.id
    assert reports[0].target_actor_id == test_user.actor.id


@pytest.mark.anyio
async def test_flag_handler_with_note(db, mock_valkey, test_user):
    """Flag with actor + note objects should link to the target note."""
    remote = await make_remote_actor(db, username="reporter2", domain="other2.example")
    note = await make_note(db, test_user.actor, content="bad content")

    from app.activitypub.handlers.flag import handle_flag

    activity = {
        "id": f"https://other2.example/flags/{uuid.uuid4()}",
        "type": "Flag",
        "actor": remote.ap_id,
        "object": [test_user.actor.ap_id, note.ap_id],
        "content": "Offensive note",
    }

    await handle_flag(db, activity)

    from app.services.report_service import list_reports
    reports = await list_reports(db)
    matching = [r for r in reports if r.comment == "Offensive note"]
    assert len(matching) == 1
    assert matching[0].target_note_id == note.id


# ── Renderer ─────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_render_flag_activity():
    from app.activitypub.renderer import render_flag_activity

    result = render_flag_activity(
        activity_id="https://local/flags/1",
        actor_ap_id="https://local/actor",
        target_actor_ap_id="https://remote/users/bad",
        note_ap_ids=["https://remote/notes/1"],
        content="spam",
    )

    assert result["type"] == "Flag"
    assert result["actor"] == "https://local/actor"
    assert "https://remote/users/bad" in result["object"]
    assert "https://remote/notes/1" in result["object"]
    assert result["content"] == "spam"


@pytest.mark.anyio
async def test_render_flag_activity_no_notes():
    from app.activitypub.renderer import render_flag_activity

    result = render_flag_activity(
        activity_id="https://local/flags/2",
        actor_ap_id="https://local/actor",
        target_actor_ap_id="https://remote/users/bad",
    )

    assert result["object"] == ["https://remote/users/bad"]
    assert result["content"] == ""


# ── Server Settings Service ──────────────────────────────────────────────────


@pytest.mark.anyio
async def test_server_settings_service(db, mock_valkey):
    from app.services.server_settings_service import get_all_settings, get_setting, set_setting

    # Set a value
    await set_setting(db, "server_name", "Test Server")
    await db.commit()

    # Get it back
    value = await get_setting(db, "server_name")
    assert value == "Test Server"

    # Get all
    all_settings = await get_all_settings(db)
    assert all_settings["server_name"] == "Test Server"


@pytest.mark.anyio
async def test_server_settings_null(db, mock_valkey):
    from app.services.server_settings_service import get_setting

    # Non-existent key should return None
    value = await get_setting(db, "nonexistent_key")
    assert value is None


# ── Instance Info uses Server Settings ────────────────────────────────────────


@pytest.mark.anyio
async def test_instance_info_uses_settings(db, app_client, mock_valkey):
    from app.services.server_settings_service import set_setting

    await set_setting(db, "server_name", "Custom Instance")
    await set_setting(db, "server_description", "A custom description")
    await db.commit()

    resp = await app_client.get("/api/v1/instance")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Custom Instance"
    assert data["description"] == "A custom description"


# ── NodeInfo uses Server Settings ─────────────────────────────────────────────


@pytest.mark.anyio
async def test_nodeinfo_uses_settings(db, app_client, mock_valkey):
    from app.services.server_settings_service import set_setting

    await set_setting(db, "server_name", "NodeInfo Test")
    await set_setting(db, "server_description", "NodeInfo desc")
    await db.commit()

    resp = await app_client.get("/nodeinfo/2.0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["metadata"]["nodeName"] == "NodeInfo Test"
    assert data["metadata"]["nodeDescription"] == "NodeInfo desc"


# ── Moderation Service Unit Tests ─────────────────────────────────────────────


@pytest.mark.anyio
async def test_log_action(db, mock_valkey):
    admin = await make_admin_user(db)
    from app.services.moderation_service import log_action

    entry = await log_action(db, admin, "test_action", "actor", "12345", "reason")
    await db.commit()

    assert entry.action == "test_action"
    assert entry.target_type == "actor"
    assert entry.target_id == "12345"
    assert entry.reason == "reason"
    assert entry.moderator_id == admin.id


@pytest.mark.anyio
async def test_force_sensitive_service(db, mock_valkey, test_user):
    admin = await make_admin_user(db)
    note = await make_note(db, test_user.actor, content="nsfw")
    assert not note.sensitive

    from app.services.moderation_service import force_sensitive

    await force_sensitive(db, note, admin)
    await db.commit()

    await db.refresh(note)
    assert note.sensitive
