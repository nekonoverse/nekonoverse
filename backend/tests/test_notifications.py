"""Tests for notification system (Phase 4)."""

import uuid
from unittest.mock import AsyncMock

import pytest

from tests.conftest import make_note, make_remote_actor


# ── Helpers ──────────────────────────────────────────────────────────────────


def authed_client_for(app_client, mock_valkey, user):
    mock_valkey.get = AsyncMock(return_value=str(user.id))
    app_client.cookies.set("nekonoverse_session", "test-session-id")
    return app_client


# ── Notification Service ─────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_create_notification(db, mock_valkey, test_user, test_user_b):
    from app.services.notification_service import create_notification

    notif = await create_notification(
        db, "mention", test_user.actor_id, test_user_b.actor_id,
    )
    await db.commit()
    assert notif is not None
    assert notif.type == "mention"
    assert notif.recipient_id == test_user.actor_id
    assert notif.sender_id == test_user_b.actor_id


@pytest.mark.anyio
async def test_no_self_notification(db, mock_valkey, test_user):
    from app.services.notification_service import create_notification

    notif = await create_notification(
        db, "mention", test_user.actor_id, test_user.actor_id,
    )
    assert notif is None


@pytest.mark.anyio
async def test_no_notification_when_blocked(db, mock_valkey, test_user, test_user_b):
    from app.services.block_service import block_actor
    from app.services.notification_service import create_notification

    # test_user blocks test_user_b
    await block_actor(db, test_user, test_user_b.actor)
    await db.commit()

    notif = await create_notification(
        db, "mention", test_user.actor_id, test_user_b.actor_id,
    )
    assert notif is None


@pytest.mark.anyio
async def test_no_notification_when_muted(db, mock_valkey, test_user, test_user_b):
    from app.services.mute_service import mute_actor
    from app.services.notification_service import create_notification

    await mute_actor(db, test_user, test_user_b.actor)
    await db.commit()

    notif = await create_notification(
        db, "mention", test_user.actor_id, test_user_b.actor_id,
    )
    assert notif is None


@pytest.mark.anyio
async def test_get_notifications(db, mock_valkey, test_user, test_user_b):
    from app.services.notification_service import create_notification, get_notifications

    await create_notification(db, "follow", test_user.actor_id, test_user_b.actor_id)
    await create_notification(db, "mention", test_user.actor_id, test_user_b.actor_id)
    await db.commit()

    notifs = await get_notifications(db, test_user.actor_id)
    assert len(notifs) >= 2
    # Most recent first
    assert notifs[0].type == "mention"


@pytest.mark.anyio
async def test_mark_as_read(db, mock_valkey, test_user, test_user_b):
    from app.services.notification_service import create_notification, mark_as_read

    notif = await create_notification(db, "follow", test_user.actor_id, test_user_b.actor_id)
    await db.commit()
    assert not notif.read

    success = await mark_as_read(db, notif.id, test_user.actor_id)
    await db.commit()
    assert success

    await db.refresh(notif)
    assert notif.read


@pytest.mark.anyio
async def test_mark_as_read_wrong_user(db, mock_valkey, test_user, test_user_b):
    from app.services.notification_service import create_notification, mark_as_read

    notif = await create_notification(db, "follow", test_user.actor_id, test_user_b.actor_id)
    await db.commit()

    # test_user_b shouldn't be able to dismiss test_user's notification
    success = await mark_as_read(db, notif.id, test_user_b.actor_id)
    assert not success


@pytest.mark.anyio
async def test_clear_notifications(db, mock_valkey, test_user, test_user_b):
    from app.services.notification_service import (
        clear_notifications,
        create_notification,
        get_notifications,
    )

    await create_notification(db, "follow", test_user.actor_id, test_user_b.actor_id)
    await create_notification(db, "mention", test_user.actor_id, test_user_b.actor_id)
    await db.commit()

    await clear_notifications(db, test_user.actor_id)
    await db.commit()

    notifs = await get_notifications(db, test_user.actor_id)
    assert len(notifs) == 0


@pytest.mark.anyio
async def test_mark_all_as_read(db, mock_valkey, test_user, test_user_b):
    from app.services.notification_service import (
        create_notification,
        get_notifications,
        mark_all_as_read,
    )

    await create_notification(db, "follow", test_user.actor_id, test_user_b.actor_id)
    await create_notification(db, "mention", test_user.actor_id, test_user_b.actor_id)
    await db.commit()

    await mark_all_as_read(db, test_user.actor_id)
    await db.commit()

    notifs = await get_notifications(db, test_user.actor_id)
    assert all(n.read for n in notifs)


@pytest.mark.anyio
async def test_duplicate_notification_skipped(db, mock_valkey, test_user, test_user_b):
    """Duplicate unread notification with same type/sender/note should be skipped."""
    from app.services.notification_service import create_notification, get_notifications

    note = await make_note(db, test_user_b.actor, content="test")
    n1 = await create_notification(
        db, "mention", test_user.actor_id, test_user_b.actor_id, note_id=note.id,
    )
    n2 = await create_notification(
        db, "mention", test_user.actor_id, test_user_b.actor_id, note_id=note.id,
    )
    await db.commit()

    assert n1 is not None
    assert n2 is None  # duplicate skipped

    notifs = await get_notifications(db, test_user.actor_id)
    mention_notifs = [n for n in notifs if n.type == "mention" and n.note_id == note.id]
    assert len(mention_notifs) == 1


@pytest.mark.anyio
async def test_duplicate_allowed_after_read(db, mock_valkey, test_user, test_user_b):
    """After marking as read, duplicate notification of the same type is still deduplicated."""
    from app.services.notification_service import (
        create_notification,
        mark_as_read,
    )

    n1 = await create_notification(
        db, "follow", test_user.actor_id, test_user_b.actor_id,
    )
    await db.commit()
    assert n1 is not None

    await mark_as_read(db, n1.id, test_user.actor_id)
    await db.commit()

    n2 = await create_notification(
        db, "follow", test_user.actor_id, test_user_b.actor_id,
    )
    await db.commit()
    assert n2 is None  # deduplicated regardless of read status


# ── Notification API ─────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_notifications_api(db, app_client, mock_valkey, test_user, test_user_b):
    client = authed_client_for(app_client, mock_valkey, test_user)

    from app.services.notification_service import create_notification
    await create_notification(db, "follow", test_user.actor_id, test_user_b.actor_id)
    await db.commit()

    resp = await client.get("/api/v1/notifications")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["type"] == "follow"
    assert data[0]["account"]["username"] == "testuser_b"


@pytest.mark.anyio
async def test_dismiss_notification_api(db, app_client, mock_valkey, test_user, test_user_b):
    client = authed_client_for(app_client, mock_valkey, test_user)

    from app.services.notification_service import create_notification
    notif = await create_notification(db, "follow", test_user.actor_id, test_user_b.actor_id)
    await db.commit()

    resp = await client.post(f"/api/v1/notifications/{notif.id}/dismiss")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_clear_notifications_api(db, app_client, mock_valkey, test_user, test_user_b):
    client = authed_client_for(app_client, mock_valkey, test_user)

    from app.services.notification_service import create_notification
    await create_notification(db, "follow", test_user.actor_id, test_user_b.actor_id)
    await db.commit()

    resp = await client.post("/api/v1/notifications/clear")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_mark_all_as_read_api(db, app_client, mock_valkey, test_user, test_user_b):
    client = authed_client_for(app_client, mock_valkey, test_user)

    from app.services.notification_service import create_notification
    await create_notification(db, "follow", test_user.actor_id, test_user_b.actor_id)
    await create_notification(db, "mention", test_user.actor_id, test_user_b.actor_id)
    await db.commit()

    resp = await client.post("/api/v1/notifications/mark_all_as_read")
    assert resp.status_code == 200

    # Verify all are now read
    resp2 = await client.get("/api/v1/notifications")
    assert resp2.status_code == 200
    for n in resp2.json():
        assert n["read"] is True


@pytest.mark.anyio
async def test_notifications_require_auth(app_client):
    resp = await app_client.get("/api/v1/notifications")
    assert resp.status_code == 401


# ── Notification Triggers ────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_reaction_creates_notification(db, app_client, mock_valkey, test_user, test_user_b):
    """Reacting to a note should create a notification for the note author."""
    note = await make_note(db, test_user.actor, content="React to me")

    client = authed_client_for(app_client, mock_valkey, test_user_b)
    resp = await client.post(f"/api/v1/statuses/{note.id}/react/👍")
    assert resp.status_code == 200

    from app.services.notification_service import get_notifications
    notifs = await get_notifications(db, test_user.actor_id)
    reaction_notifs = [n for n in notifs if n.type == "reaction"]
    assert len(reaction_notifs) >= 1
    assert reaction_notifs[0].reaction_emoji == "👍"


@pytest.mark.anyio
async def test_reblog_creates_notification(db, app_client, mock_valkey, test_user, test_user_b):
    """Reblogging a note should create a notification for the note author."""
    note = await make_note(db, test_user.actor, content="Reblog me")

    client = authed_client_for(app_client, mock_valkey, test_user_b)
    resp = await client.post(f"/api/v1/statuses/{note.id}/reblog")
    assert resp.status_code == 200

    from app.services.notification_service import get_notifications
    notifs = await get_notifications(db, test_user.actor_id)
    renote_notifs = [n for n in notifs if n.type == "renote"]
    assert len(renote_notifs) >= 1


@pytest.mark.anyio
async def test_follow_creates_notification(db, app_client, mock_valkey, test_user, test_user_b):
    """Following a user should create a notification."""
    client = authed_client_for(app_client, mock_valkey, test_user)
    resp = await client.post(f"/api/v1/accounts/{test_user_b.actor_id}/follow")
    assert resp.status_code == 200

    from app.services.notification_service import get_notifications
    notifs = await get_notifications(db, test_user_b.actor_id)
    follow_notifs = [n for n in notifs if n.type == "follow"]
    assert len(follow_notifs) >= 1
