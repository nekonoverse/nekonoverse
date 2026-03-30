"""Tests for the notification service layer."""

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

from app.services.notification_service import (
    clear_notifications,
    create_notification,
    get_notifications,
    get_unread_count,
    mark_all_as_read,
    mark_as_read,
)
from tests.conftest import make_note


@patch("app.services.push_service.send_web_push", new_callable=AsyncMock)
async def test_create_notification_basic(mock_push, db, test_user, test_user_b):
    note = await make_note(db, test_user_b.actor)
    notif = await create_notification(
        db,
        type="mention",
        recipient_id=test_user.actor_id,
        sender_id=test_user_b.actor_id,
        note_id=note.id,
    )

    assert notif is not None
    assert notif.type == "mention"
    assert notif.recipient_id == test_user.actor_id
    assert notif.sender_id == test_user_b.actor_id
    assert notif.note_id == note.id
    assert notif.read is False


@patch("app.services.push_service.send_web_push", new_callable=AsyncMock)
async def test_create_notification_self_returns_none(mock_push, db, test_user):
    note = await make_note(db, test_user.actor)
    notif = await create_notification(
        db,
        type="mention",
        recipient_id=test_user.actor_id,
        sender_id=test_user.actor_id,
        note_id=note.id,
    )

    assert notif is None


@patch("app.services.push_service.send_web_push", new_callable=AsyncMock)
@patch("app.services.block_service.is_blocking", new_callable=AsyncMock, return_value=True)
async def test_create_notification_blocked_returns_none(
    mock_blocking, mock_push, db, test_user, test_user_b
):
    notif = await create_notification(
        db,
        type="favourite",
        recipient_id=test_user.actor_id,
        sender_id=test_user_b.actor_id,
    )

    assert notif is None
    mock_blocking.assert_awaited_once_with(db, test_user.actor_id, test_user_b.actor_id)


@patch("app.services.push_service.send_web_push", new_callable=AsyncMock)
@patch("app.services.block_service.is_blocking", new_callable=AsyncMock, return_value=False)
@patch("app.services.mute_service.is_muting", new_callable=AsyncMock, return_value=True)
async def test_create_notification_muted_returns_none(
    mock_muting, mock_blocking, mock_push, db, test_user, test_user_b
):
    notif = await create_notification(
        db,
        type="favourite",
        recipient_id=test_user.actor_id,
        sender_id=test_user_b.actor_id,
    )

    assert notif is None
    mock_muting.assert_awaited_once_with(db, test_user.actor_id, test_user_b.actor_id)


@patch("app.services.push_service.send_web_push", new_callable=AsyncMock)
async def test_create_notification_duplicate_returns_none(
    mock_push, db, test_user, test_user_b
):
    note = await make_note(db, test_user_b.actor)
    first = await create_notification(
        db,
        type="mention",
        recipient_id=test_user.actor_id,
        sender_id=test_user_b.actor_id,
        note_id=note.id,
    )
    assert first is not None

    duplicate = await create_notification(
        db,
        type="mention",
        recipient_id=test_user.actor_id,
        sender_id=test_user_b.actor_id,
        note_id=note.id,
    )
    assert duplicate is None


@patch("app.services.push_service.send_web_push", new_callable=AsyncMock)
async def test_get_notifications_empty(mock_push, db, test_user):
    result = await get_notifications(db, test_user.actor_id)
    assert result == []


@patch("app.services.push_service.send_web_push", new_callable=AsyncMock)
async def test_get_notifications_returns_ordered(mock_push, db, test_user, test_user_b):
    note = await make_note(db, test_user_b.actor)

    await create_notification(
        db, type="mention", recipient_id=test_user.actor_id,
        sender_id=test_user_b.actor_id, note_id=note.id,
    )
    await asyncio.sleep(0.01)
    await create_notification(
        db, type="favourite", recipient_id=test_user.actor_id,
        sender_id=test_user_b.actor_id, note_id=note.id,
    )

    result = await get_notifications(db, test_user.actor_id)
    assert len(result) == 2
    # created_at descでソートされるため、最新が先頭
    assert result[0].type == "favourite"
    assert result[1].type == "mention"


@patch("app.services.push_service.send_web_push", new_callable=AsyncMock)
async def test_get_notifications_filter_by_type(mock_push, db, test_user, test_user_b):
    note = await make_note(db, test_user_b.actor)

    await create_notification(
        db, type="mention", recipient_id=test_user.actor_id,
        sender_id=test_user_b.actor_id, note_id=note.id,
    )
    await asyncio.sleep(0.01)
    await create_notification(
        db, type="favourite", recipient_id=test_user.actor_id,
        sender_id=test_user_b.actor_id, note_id=note.id,
    )

    result = await get_notifications(db, test_user.actor_id, types=["mention"])
    assert len(result) == 1
    assert result[0].type == "mention"


@patch("app.services.push_service.send_web_push", new_callable=AsyncMock)
async def test_mark_as_read_success(mock_push, db, test_user, test_user_b):
    notif = await create_notification(
        db, type="follow", recipient_id=test_user.actor_id,
        sender_id=test_user_b.actor_id,
    )
    assert notif is not None
    assert notif.read is False

    success = await mark_as_read(db, notif.id, test_user.actor_id)
    assert success is True


@patch("app.services.push_service.send_web_push", new_callable=AsyncMock)
async def test_mark_as_read_not_found(mock_push, db, test_user):
    success = await mark_as_read(db, uuid.uuid4(), test_user.actor_id)
    assert success is False


@patch("app.services.push_service.send_web_push", new_callable=AsyncMock)
async def test_mark_all_as_read(mock_push, db, test_user, test_user_b):
    note = await make_note(db, test_user_b.actor)
    await create_notification(
        db, type="mention", recipient_id=test_user.actor_id,
        sender_id=test_user_b.actor_id, note_id=note.id,
    )
    await asyncio.sleep(0.01)
    await create_notification(
        db, type="favourite", recipient_id=test_user.actor_id,
        sender_id=test_user_b.actor_id, note_id=note.id,
    )

    await mark_all_as_read(db, test_user.actor_id)

    result = await get_notifications(db, test_user.actor_id)
    assert all(n.read for n in result)


@patch("app.services.push_service.send_web_push", new_callable=AsyncMock)
async def test_clear_notifications(mock_push, db, test_user, test_user_b):
    await create_notification(
        db, type="follow", recipient_id=test_user.actor_id,
        sender_id=test_user_b.actor_id,
    )

    await clear_notifications(db, test_user.actor_id)

    result = await get_notifications(db, test_user.actor_id)
    assert result == []


@patch("app.services.push_service.send_web_push", new_callable=AsyncMock)
async def test_get_unread_count(mock_push, db, test_user, test_user_b):
    note = await make_note(db, test_user_b.actor)

    await create_notification(
        db, type="mention", recipient_id=test_user.actor_id,
        sender_id=test_user_b.actor_id, note_id=note.id,
    )
    await asyncio.sleep(0.01)
    await create_notification(
        db, type="favourite", recipient_id=test_user.actor_id,
        sender_id=test_user_b.actor_id, note_id=note.id,
    )
    await asyncio.sleep(0.01)
    await create_notification(
        db, type="follow", recipient_id=test_user.actor_id,
        sender_id=test_user_b.actor_id,
    )

    counts = await get_unread_count(db, test_user.actor_id)
    assert counts["total"] == 3
    assert counts["mentions"] == 1
    assert counts["other"] == 2
