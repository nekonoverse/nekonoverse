"""Tests for follow requests API endpoints."""

import uuid
from unittest.mock import AsyncMock, patch

from app.models.follow import Follow


async def test_list_follow_requests_empty(authed_client, test_user, db):
    """Returns empty list when no pending follow requests."""
    resp = await authed_client.get("/api/v1/follow_requests")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_follow_requests_returns_pending(
    authed_client, test_user, test_user_b, db
):
    """Returns pending follow requests addressed to the current user."""
    follow = Follow(
        follower_id=test_user_b.actor_id,
        following_id=test_user.actor_id,
        accepted=False,
    )
    db.add(follow)
    await db.flush()

    resp = await authed_client.get("/api/v1/follow_requests")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == str(test_user_b.actor_id)
    assert data[0]["username"] == "testuser_b"


async def test_list_follow_requests_unauthenticated(app_client):
    """Unauthenticated request is rejected."""
    resp = await app_client.get("/api/v1/follow_requests")
    assert resp.status_code in (401, 403)


@patch("app.services.push_service.send_web_push", new_callable=AsyncMock)
@patch("app.services.delivery_service.enqueue_delivery", new_callable=AsyncMock)
async def test_authorize_follow_request(
    mock_delivery, mock_push, authed_client, test_user, test_user_b, db
):
    """Authorizing a pending follow request sets accepted=True."""
    follow = Follow(
        follower_id=test_user_b.actor_id,
        following_id=test_user.actor_id,
        accepted=False,
    )
    db.add(follow)
    await db.flush()

    resp = await authed_client.post(
        f"/api/v1/follow_requests/{test_user_b.actor_id}/authorize"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(test_user_b.actor_id)
    assert data["followed_by"] is True

    # follow.accepted が True に更新されたことを確認
    await db.refresh(follow)
    assert follow.accepted is True


async def test_authorize_follow_request_not_found(authed_client, test_user, db):
    """Authorizing a non-existent follow request returns 404."""
    fake_id = uuid.uuid4()
    resp = await authed_client.post(
        f"/api/v1/follow_requests/{fake_id}/authorize"
    )
    assert resp.status_code == 404


@patch("app.services.push_service.send_web_push", new_callable=AsyncMock)
@patch("app.services.delivery_service.enqueue_delivery", new_callable=AsyncMock)
async def test_reject_follow_request(
    mock_delivery, mock_push, authed_client, test_user, test_user_b, db
):
    """Rejecting a pending follow request deletes the Follow record."""
    follow = Follow(
        follower_id=test_user_b.actor_id,
        following_id=test_user.actor_id,
        accepted=False,
    )
    db.add(follow)
    await db.flush()
    follow_id = follow.id

    resp = await authed_client.post(
        f"/api/v1/follow_requests/{test_user_b.actor_id}/reject"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(test_user_b.actor_id)
    assert data["followed_by"] is False

    # Follow レコードが削除されたことを確認
    from sqlalchemy import select

    result = await db.execute(select(Follow).where(Follow.id == follow_id))
    assert result.scalar_one_or_none() is None


async def test_reject_follow_request_not_found(authed_client, test_user, db):
    """Rejecting a non-existent follow request returns 404."""
    fake_id = uuid.uuid4()
    resp = await authed_client.post(
        f"/api/v1/follow_requests/{fake_id}/reject"
    )
    assert resp.status_code == 404
