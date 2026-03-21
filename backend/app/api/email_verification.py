"""Email verification and password reset API endpoints."""

from uuid import UUID

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.user import User

router = APIRouter(prefix="/api/v1", tags=["email"])


class ChangeEmailRequest(BaseModel):
    email: EmailStr
    password: str


class ConfirmEmailRequest(BaseModel):
    token: str
    uid: UUID


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    uid: UUID
    password: str


@router.post("/email/change")
async def change_email(
    body: ChangeEmailRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change email address. Requires password confirmation."""
    if not bcrypt.checkpw(body.password.encode(), user.password_hash.encode()):
        raise HTTPException(status_code=403, detail="Incorrect password")

    # Check if email is already in use by another user
    result = await db.execute(
        select(User).where(User.email == body.email, User.id != user.id)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already in use")

    user.email = body.email
    user.email_verified = False
    user.email_verification_token = None

    if settings.email_enabled:
        from app.services.email_service import send_verification_email

        await send_verification_email(db, user)

    await db.commit()
    return {"message": "Email updated. Please check your inbox for verification."}


@router.post("/email/verify")
async def resend_verification(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Resend verification email. Rate limited to once per 5 minutes."""
    if not settings.email_enabled:
        raise HTTPException(status_code=422, detail="Email is not configured on this server")

    if user.email_verified:
        return {"message": "Email already verified"}

    from app.services.email_service import send_verification_email

    sent = await send_verification_email(db, user)
    if not sent:
        raise HTTPException(status_code=429, detail="Please wait before requesting again")
    await db.commit()
    return {"message": "Verification email sent"}


@router.post("/email/confirm")
async def confirm_email(
    body: ConfirmEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    """Confirm email with token. No auth required."""
    from app.services.email_service import verify_email_token

    success = await verify_email_token(db, body.uid, body.token)
    if not success:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    await db.commit()
    return {"message": "Email verified successfully"}


@router.post("/auth/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Send password reset email. Always returns 200 to not leak email existence."""
    if not settings.email_enabled:
        raise HTTPException(status_code=422, detail="Email is not configured on this server")

    # Rate limit by IP
    from app.valkey_client import valkey

    client_ip = request.client.host if request.client else "unknown"
    rl_key = f"forgot_password:{client_ip}"
    attempts = await valkey.get(rl_key)
    if attempts is not None and int(attempts) >= 5:
        # Still return 200 to not reveal anything
        return {"message": "If an account with that email exists, a reset link has been sent"}
    await valkey.incr(rl_key)
    await valkey.expire(rl_key, 300)

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user:
        from app.services.email_service import send_password_reset_email

        await send_password_reset_email(db, user)
        await db.commit()

    return {"message": "If an account with that email exists, a reset link has been sent"}


@router.post("/auth/reset-password")
async def reset_password(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Reset password with token."""
    if len(body.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")

    from app.services.email_service import verify_reset_token

    user = await verify_reset_token(db, body.uid, body.token)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    user.password_hash = bcrypt.hashpw(
        body.password.encode(), bcrypt.gensalt()
    ).decode()
    user.password_reset_token = None
    await db.commit()

    return {"message": "Password has been reset successfully"}
