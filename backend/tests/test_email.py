"""Tests for email verification and password reset."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.models.user import User


async def test_verify_credentials_includes_email_verified(authed_client, test_user):
    """verify_credentials should include email_verified field."""
    resp = await authed_client.get("/api/v1/accounts/verify_credentials")
    assert resp.status_code == 200
    data = resp.json()
    assert "email_verified" in data
    assert isinstance(data["email_verified"], bool)


async def test_resend_verification_requires_auth(app_client):
    """POST /email/verify requires authentication."""
    resp = await app_client.post("/api/v1/email/verify")
    assert resp.status_code in (401, 403)


async def test_resend_verification_when_smtp_disabled(authed_client):
    """Resend should fail when SMTP is not configured."""
    resp = await authed_client.post("/api/v1/email/verify")
    assert resp.status_code == 422
    assert "not configured" in resp.json()["detail"]


async def test_resend_verification_already_verified(authed_client, test_user, db):
    """Resend should return message when already verified."""
    test_user.email_verified = True
    await db.flush()

    with patch("app.api.email_verification.settings") as mock_settings:
        mock_settings.email_enabled = True
        resp = await authed_client.post("/api/v1/email/verify")
    assert resp.status_code == 200
    assert "already verified" in resp.json()["message"]


async def test_confirm_email_invalid_token(app_client, test_user):
    """Invalid token should return 400."""
    resp = await app_client.post(
        "/api/v1/email/confirm",
        json={"token": "invalid-token", "uid": str(test_user.id)},
    )
    assert resp.status_code == 400


async def test_confirm_email_success(app_client, test_user, db):
    """Valid token should verify the email."""
    import secrets

    token = secrets.token_urlsafe(32)
    test_user.email_verification_token = token
    test_user.email_verification_sent_at = datetime.now(timezone.utc)
    test_user.email_verified = False
    await db.flush()

    resp = await app_client.post(
        "/api/v1/email/confirm",
        json={"token": token, "uid": str(test_user.id)},
    )
    assert resp.status_code == 200
    assert "verified" in resp.json()["message"]

    result = await db.execute(select(User).where(User.id == test_user.id))
    user = result.scalar_one()
    assert user.email_verified is True
    assert user.email_verification_token is None


async def test_confirm_email_expired_token(app_client, test_user, db):
    """Expired token (>24h) should return 400."""
    import secrets

    token = secrets.token_urlsafe(32)
    test_user.email_verification_token = token
    test_user.email_verification_sent_at = datetime.now(timezone.utc) - timedelta(hours=25)
    test_user.email_verified = False
    await db.flush()

    resp = await app_client.post(
        "/api/v1/email/confirm",
        json={"token": token, "uid": str(test_user.id)},
    )
    assert resp.status_code == 400


async def test_forgot_password_always_returns_200(app_client, mock_valkey):
    """forgot-password should always return 200 regardless of email existence."""
    with patch("app.api.email_verification.settings") as mock_settings:
        mock_settings.email_enabled = True
        resp = await app_client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "nonexistent@example.com"},
        )
    assert resp.status_code == 200


async def test_forgot_password_smtp_disabled(app_client, mock_valkey):
    """forgot-password should fail when SMTP is not configured."""
    resp = await app_client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "test@example.com"},
    )
    assert resp.status_code == 422


async def test_reset_password_invalid_token(app_client, test_user):
    """Invalid reset token should return 400."""
    resp = await app_client.post(
        "/api/v1/auth/reset-password",
        json={
            "token": "invalid-token",
            "uid": str(test_user.id),
            "password": "newpassword123",
        },
    )
    assert resp.status_code == 400


async def test_reset_password_success(app_client, test_user, db):
    """Valid reset token should change password."""
    import secrets

    token = secrets.token_urlsafe(32)
    test_user.password_reset_token = token
    test_user.password_reset_sent_at = datetime.now(timezone.utc)
    await db.flush()

    resp = await app_client.post(
        "/api/v1/auth/reset-password",
        json={
            "token": token,
            "uid": str(test_user.id),
            "password": "newpassword123",
        },
    )
    assert resp.status_code == 200

    result = await db.execute(select(User).where(User.id == test_user.id))
    user = result.scalar_one()
    assert user.password_reset_token is None

    # Verify login with new password works
    import bcrypt
    assert bcrypt.checkpw(b"newpassword123", user.password_hash.encode())


async def test_reset_password_expired_token(app_client, test_user, db):
    """Expired reset token (>1h) should return 400."""
    import secrets

    token = secrets.token_urlsafe(32)
    test_user.password_reset_token = token
    test_user.password_reset_sent_at = datetime.now(timezone.utc) - timedelta(hours=2)
    await db.flush()

    resp = await app_client.post(
        "/api/v1/auth/reset-password",
        json={
            "token": token,
            "uid": str(test_user.id),
            "password": "newpassword123",
        },
    )
    assert resp.status_code == 400


async def test_reset_password_too_short(app_client, test_user, db):
    """Password must be at least 8 characters."""
    import secrets

    token = secrets.token_urlsafe(32)
    test_user.password_reset_token = token
    test_user.password_reset_sent_at = datetime.now(timezone.utc)
    await db.flush()

    resp = await app_client.post(
        "/api/v1/auth/reset-password",
        json={
            "token": token,
            "uid": str(test_user.id),
            "password": "short",
        },
    )
    assert resp.status_code == 422


async def test_email_service_token_generation(db, test_user):
    """Email service should generate unique tokens."""
    from app.services.email_service import RESEND_COOLDOWN

    test_user.email_verified = False
    test_user.email_verification_token = None
    test_user.email_verification_sent_at = None
    await db.flush()

    with patch("app.services.email_service.settings") as mock_settings:
        mock_settings.email_enabled = True
        mock_settings.frontend_url = "http://localhost:3000"
        with patch("app.services.email_queue.valkey_client") as mock_valkey:
            mock_valkey.lpush = AsyncMock()
            from app.services.email_service import send_verification_email
            result = await send_verification_email(db, test_user)

    assert result is True
    assert test_user.email_verification_token is not None
    assert test_user.email_verification_sent_at is not None


async def test_email_service_cooldown(db, test_user):
    """Email should not be resent within cooldown period."""
    test_user.email_verified = False
    test_user.email_verification_sent_at = datetime.now(timezone.utc)
    await db.flush()

    with patch("app.services.email_service.settings") as mock_settings:
        mock_settings.email_enabled = True
        from app.services.email_service import send_verification_email
        result = await send_verification_email(db, test_user)

    assert result is False
