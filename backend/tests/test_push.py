"""Tests for Web Push subscription API and push service."""

from unittest.mock import AsyncMock, patch

# ── Helpers ──────────────────────────────────────────────────────────────────


def authed_client_for(app_client, mock_valkey, user, session_id="test-session-id"):
    mock_valkey.get = AsyncMock(return_value=str(user.id))
    app_client.cookies.set("nekonoverse_session", session_id)
    return app_client


# ── VAPID Key ────────────────────────────────────────────────────────────────


def test_vapid_public_key_generation():
    """VAPID public key should be a valid base64url string."""
    import base64

    from app.services.push_service import get_vapid_public_key_base64url

    key = get_vapid_public_key_base64url()
    assert isinstance(key, str)
    assert len(key) > 0
    # Should be decodable as base64url
    raw = base64.urlsafe_b64decode(key + "==")
    # Uncompressed EC point: 0x04 + 32 bytes x + 32 bytes y = 65 bytes
    assert len(raw) == 65
    assert raw[0] == 0x04


def test_vapid_key_deterministic():
    """Same SECRET_KEY should produce same VAPID key pair."""
    from app.services.push_service import get_vapid_public_key_base64url

    key1 = get_vapid_public_key_base64url()
    key2 = get_vapid_public_key_base64url()
    assert key1 == key2


# ── Subscription CRUD (Service) ──────────────────────────────────────────────



async def test_create_subscription(db, test_user):
    from app.services.push_service import create_subscription, get_subscription_by_session

    sub = await create_subscription(
        db,
        actor_id=test_user.actor_id,
        session_id="sess-1",
        endpoint="https://push.example.com/sub1",
        key_p256dh="test-p256dh-key",
        key_auth="test-auth-key",
    )
    await db.commit()

    assert sub is not None
    assert sub.endpoint == "https://push.example.com/sub1"
    assert sub.alerts["mention"] is True

    fetched = await get_subscription_by_session(db, "sess-1")
    assert fetched is not None
    assert fetched.id == sub.id



async def test_create_replaces_existing(db, test_user):
    from app.services.push_service import create_subscription, get_subscription_by_session

    await create_subscription(
        db,
        actor_id=test_user.actor_id,
        session_id="sess-replace",
        endpoint="https://push.example.com/old",
        key_p256dh="key1",
        key_auth="auth1",
    )
    await db.commit()

    sub2 = await create_subscription(
        db,
        actor_id=test_user.actor_id,
        session_id="sess-replace",
        endpoint="https://push.example.com/new",
        key_p256dh="key2",
        key_auth="auth2",
    )
    await db.commit()

    fetched = await get_subscription_by_session(db, "sess-replace")
    assert fetched.endpoint == "https://push.example.com/new"
    assert fetched.id == sub2.id



async def test_update_subscription_alerts(db, test_user):
    from app.services.push_service import create_subscription, update_subscription_alerts

    await create_subscription(
        db,
        actor_id=test_user.actor_id,
        session_id="sess-update",
        endpoint="https://push.example.com/sub",
        key_p256dh="key",
        key_auth="auth",
    )
    await db.commit()

    updated = await update_subscription_alerts(
        db, "sess-update", alerts={"mention": False, "follow": False}
    )
    assert updated is not None
    assert updated.alerts["mention"] is False
    assert updated.alerts["follow"] is False
    assert updated.alerts["reblog"] is True  # unchanged



async def test_delete_subscription(db, test_user):
    from app.services.push_service import (
        create_subscription,
        delete_subscription,
        get_subscription_by_session,
    )

    await create_subscription(
        db,
        actor_id=test_user.actor_id,
        session_id="sess-del",
        endpoint="https://push.example.com/sub",
        key_p256dh="key",
        key_auth="auth",
    )
    await db.commit()

    deleted = await delete_subscription(db, "sess-del")
    assert deleted is True

    fetched = await get_subscription_by_session(db, "sess-del")
    assert fetched is None


# ── Push API Endpoints ───────────────────────────────────────────────────────



async def test_create_push_subscription_api(app_client, test_user, mock_valkey):
    client = authed_client_for(app_client, mock_valkey, test_user)
    resp = await client.post(
        "/api/v1/push/subscription",
        json={
            "subscription": {
                "endpoint": "https://push.example.com/api",
                "keys": {"p256dh": "test-p256dh", "auth": "test-auth"},
            },
            "data": {
                "alerts": {"mention": True, "follow": True, "favourite": False},
            },
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["endpoint"] == "https://push.example.com/api"
    assert data["alerts"]["mention"] is True
    assert data["alerts"]["favourite"] is False
    assert "server_key" in data



async def test_get_push_subscription_api(app_client, test_user, mock_valkey):
    client = authed_client_for(app_client, mock_valkey, test_user, "sess-get-api")
    # Create first
    await client.post(
        "/api/v1/push/subscription",
        json={
            "subscription": {
                "endpoint": "https://push.example.com/get",
                "keys": {"p256dh": "p256dh", "auth": "auth"},
            },
        },
    )
    # Get
    resp = await client.get("/api/v1/push/subscription")
    assert resp.status_code == 200
    assert resp.json()["endpoint"] == "https://push.example.com/get"



async def test_get_push_subscription_404(app_client, test_user, mock_valkey):
    client = authed_client_for(app_client, mock_valkey, test_user, "sess-no-sub")
    resp = await client.get("/api/v1/push/subscription")
    assert resp.status_code == 404



async def test_update_push_subscription_api(app_client, test_user, mock_valkey):
    client = authed_client_for(app_client, mock_valkey, test_user, "sess-put-api")
    await client.post(
        "/api/v1/push/subscription",
        json={
            "subscription": {
                "endpoint": "https://push.example.com/put",
                "keys": {"p256dh": "p256dh", "auth": "auth"},
            },
        },
    )
    resp = await client.put(
        "/api/v1/push/subscription",
        json={"data": {"alerts": {"mention": False}, "policy": "followed"}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["alerts"]["mention"] is False
    assert data["policy"] == "followed"



async def test_delete_push_subscription_api(app_client, test_user, mock_valkey):
    client = authed_client_for(app_client, mock_valkey, test_user, "sess-del-api")
    await client.post(
        "/api/v1/push/subscription",
        json={
            "subscription": {
                "endpoint": "https://push.example.com/del",
                "keys": {"p256dh": "p256dh", "auth": "auth"},
            },
        },
    )
    resp = await client.delete("/api/v1/push/subscription")
    assert resp.status_code == 200
    assert resp.json() == {}

    # Should be gone
    resp = await client.get("/api/v1/push/subscription")
    assert resp.status_code == 404



async def test_push_requires_auth(app_client, mock_valkey):
    resp = await app_client.get("/api/v1/push/subscription")
    assert resp.status_code == 401


# ── Push Delivery ────────────────────────────────────────────────────────────



async def test_send_web_push_filters_alerts(db, test_user):
    """Push should not be sent if alert type is disabled."""
    from app.services.push_service import create_subscription, send_web_push

    await create_subscription(
        db,
        actor_id=test_user.actor_id,
        session_id="sess-alert-filter",
        endpoint="https://push.example.com/filtered",
        key_p256dh="key",
        key_auth="auth",
        alerts={"mention": False, "follow": True, "favourite": True, "reblog": True, "poll": True},
    )
    await db.commit()

    with (
        patch("pywebpush.webpush") as mock_wp,
        patch("app.services.push_service.is_push_enabled", return_value=True),
    ):
        await send_web_push(
            db,
            recipient_id=test_user.actor_id,
            notification_type="mention",
            sender_display_name="Sender",
        )
        # mention is disabled, so webpush should not be called
        mock_wp.assert_not_called()



async def test_send_web_push_calls_webpush(db, test_user):
    """Push should call pywebpush when alert is enabled."""
    from app.services.push_service import create_subscription, send_web_push

    await create_subscription(
        db,
        actor_id=test_user.actor_id,
        session_id="sess-push-call",
        endpoint="https://push.example.com/push",
        key_p256dh="key",
        key_auth="auth",
    )
    await db.commit()

    with (
        patch("pywebpush.webpush") as mock_wp,
        patch("app.services.push_service.is_push_enabled", return_value=True),
    ):
        await send_web_push(
            db,
            recipient_id=test_user.actor_id,
            notification_type="follow",
            sender_display_name="Alice",
            notification_id="notif-123",
        )
        mock_wp.assert_called_once()
        call_kwargs = mock_wp.call_args
        assert call_kwargs[1]["subscription_info"]["endpoint"] == "https://push.example.com/push"



async def test_send_web_push_removes_stale_410(db, test_user):
    """410 Gone should trigger automatic subscription removal."""
    from pywebpush import WebPushException

    from app.services.push_service import (
        create_subscription,
        get_subscription_by_session,
        send_web_push,
    )

    await create_subscription(
        db,
        actor_id=test_user.actor_id,
        session_id="sess-stale",
        endpoint="https://push.example.com/stale",
        key_p256dh="key",
        key_auth="auth",
    )
    await db.commit()

    # 410 Goneレスポンスをシミュレート
    mock_response = type("Response", (), {"status_code": 410})()
    error = WebPushException("Gone", response=mock_response)

    with (
        patch("pywebpush.webpush", side_effect=error),
        patch("app.services.push_service.is_push_enabled", return_value=True),
    ):
        await send_web_push(
            db,
            recipient_id=test_user.actor_id,
            notification_type="follow",
            sender_display_name="Bob",
        )

    fetched = await get_subscription_by_session(db, "sess-stale")
    assert fetched is None



async def test_send_web_push_policy_filter(db, test_user, test_user_b):
    """Push with policy='followed' should only send if recipient follows sender."""
    from app.services.push_service import create_subscription, send_web_push

    await create_subscription(
        db,
        actor_id=test_user.actor_id,
        session_id="sess-policy",
        endpoint="https://push.example.com/policy",
        key_p256dh="key",
        key_auth="auth",
        policy="followed",
    )
    await db.commit()

    with (
        patch("pywebpush.webpush") as mock_wp,
        patch("app.services.push_service.is_push_enabled", return_value=True),
    ):
        await send_web_push(
            db,
            recipient_id=test_user.actor_id,
            notification_type="follow",
            sender_display_name="User B",
            sender_id=test_user_b.actor_id,
        )
        # test_user does not follow test_user_b, so push should be skipped
        mock_wp.assert_not_called()
