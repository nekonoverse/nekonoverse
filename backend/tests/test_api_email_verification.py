"""Tests for email verification and password reset API endpoints."""

import uuid
from unittest.mock import AsyncMock, patch


@patch(
    "app.api.email_verification._check_rate_limit",
    new_callable=AsyncMock,
    return_value=True,
)
@patch(
    "app.services.email_service.send_verification_email",
    new_callable=AsyncMock,
    return_value=True,
)
async def test_change_email_success(
    mock_send, mock_rate, authed_client, test_user, db
):
    """POST /api/v1/email/change updates email with correct password."""
    resp = await authed_client.post(
        "/api/v1/email/change",
        json={"email": "newemail@example.com", "password": "password1234"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "Email updated" in data["message"]


async def test_change_email_wrong_password(authed_client, test_user, db):
    """POST /api/v1/email/change returns 403 with incorrect password."""
    resp = await authed_client.post(
        "/api/v1/email/change",
        json={"email": "newemail@example.com", "password": "wrongpassword"},
    )
    assert resp.status_code == 403
    assert "Incorrect password" in resp.json()["detail"]


@patch(
    "app.api.email_verification._check_rate_limit",
    new_callable=AsyncMock,
    return_value=True,
)
@patch(
    "app.services.email_service.verify_email_token",
    new_callable=AsyncMock,
    return_value=False,
)
async def test_confirm_email_invalid_token(
    mock_verify, mock_rate, app_client, db
):
    """POST /api/v1/email/confirm returns 400 for invalid token."""
    resp = await app_client.post(
        "/api/v1/email/confirm",
        json={"token": "invalidtoken", "uid": str(uuid.uuid4())},
    )
    assert resp.status_code == 400
    assert "Invalid or expired token" in resp.json()["detail"]


@patch(
    "app.api.email_verification._check_rate_limit",
    new_callable=AsyncMock,
    return_value=True,
)
@patch(
    "app.services.email_service.send_password_reset_email",
    new_callable=AsyncMock,
    return_value=True,
)
async def test_forgot_password_always_200(
    mock_send, mock_rate, app_client, db
):
    """POST /api/v1/auth/forgot-password always returns 200 regardless of email existence.

    This prevents email enumeration attacks.
    """
    # メールが設定されている必要がある
    with patch("app.api.email_verification.settings") as mock_settings:
        mock_settings.email_enabled = True
        resp = await app_client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "nonexistent@example.com"},
        )
    assert resp.status_code == 200
    assert "reset link has been sent" in resp.json()["message"]


@patch(
    "app.api.email_verification._check_rate_limit",
    new_callable=AsyncMock,
    return_value=True,
)
@patch(
    "app.services.email_service.verify_reset_token",
    new_callable=AsyncMock,
    return_value=None,
)
async def test_reset_password_invalid_token(
    mock_verify, mock_rate, app_client, db
):
    """POST /api/v1/auth/reset-password returns 400 for invalid token."""
    resp = await app_client.post(
        "/api/v1/auth/reset-password",
        json={
            "token": "badtoken",
            "uid": str(uuid.uuid4()),
            "password": "newpassword123",
        },
    )
    assert resp.status_code == 400
    assert "Invalid or expired token" in resp.json()["detail"]


@patch(
    "app.api.email_verification._check_rate_limit",
    new_callable=AsyncMock,
    return_value=True,
)
async def test_reset_password_short_password(mock_rate, app_client, db):
    """POST /api/v1/auth/reset-password returns 422 for password shorter than 8 chars."""
    resp = await app_client.post(
        "/api/v1/auth/reset-password",
        json={
            "token": "sometoken",
            "uid": str(uuid.uuid4()),
            "password": "short",
        },
    )
    assert resp.status_code == 422
    assert "at least 8 characters" in resp.json()["detail"]
