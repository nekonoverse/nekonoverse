"""Tests for follow_requests API — authorize creates follow notification."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.follow import Follow
from app.models.notification import Notification
from app.services.follow_service import follow_actor


async def test_authorize_creates_follow_notification(db, mock_valkey, app_client, test_user, test_user_b):
    """Authorizing a follow request creates a 'follow' notification for the target."""
    # Lock target account
    test_user.actor.manually_approves_followers = True
    await db.flush()

    # Create pending follow from test_user_b to test_user
    follow = await follow_actor(db, test_user_b, test_user.actor)
    assert follow.accepted is False

    # The follow_request notification should exist
    result = await db.execute(
        select(Notification).where(
            Notification.type == "follow_request",
            Notification.recipient_id == test_user.actor_id,
            Notification.sender_id == test_user_b.actor_id,
        )
    )
    assert result.scalar_one_or_none() is not None

    # Authorize as test_user (the target)
    session_id = "test-session-authorize"
    mock_valkey.get = AsyncMock(return_value=str(test_user.id))
    app_client.cookies.set("nekonoverse_session", session_id)

    resp = await app_client.post(f"/api/v1/follow_requests/{test_user_b.actor_id}/authorize")
    assert resp.status_code == 200

    # Verify follow is now accepted
    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == test_user_b.actor_id,
            Follow.following_id == test_user.actor_id,
        )
    )
    f = result.scalar_one()
    assert f.accepted is True

    # Verify a "follow" notification was created
    result = await db.execute(
        select(Notification).where(
            Notification.type == "follow",
            Notification.recipient_id == test_user.actor_id,
            Notification.sender_id == test_user_b.actor_id,
        )
    )
    follow_notif = result.scalar_one_or_none()
    assert follow_notif is not None
