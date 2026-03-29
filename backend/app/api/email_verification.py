"""メール認証とパスワードリセット API エンドポイント。"""

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

# レート制限定数
TOKEN_VERIFY_MAX_ATTEMPTS = 10  # IPあたりのウィンドウ内最大試行回数
TOKEN_VERIFY_WINDOW = 900  # 15分
EMAIL_SEND_MAX_PER_IP = 5  # IPあたりのウィンドウ内最大送信数
EMAIL_SEND_WINDOW = 900  # 15分


async def _check_rate_limit(key: str, max_attempts: int, window: int) -> bool:
    """Valkey ベースのレート制限を確認する。制限内なら True、超過なら False を返す。"""
    from app.valkey_client import valkey

    attempts = await valkey.get(key)
    if attempts is not None and int(attempts) >= max_attempts:
        return False
    await valkey.incr(key)
    await valkey.expire(key, window)
    return True


def _get_client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


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
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """メールアドレスを変更する。パスワードの再確認が必要。"""
    if not bcrypt.checkpw(body.password.encode(), user.password_hash.encode()):
        raise HTTPException(status_code=403, detail="Incorrect password")

    # メールアドレスが他のユーザーに使用されていないか確認
    result = await db.execute(
        select(User).where(User.email == body.email, User.id != user.id)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already in use")

    user.email = body.email
    user.email_verified = False
    user.email_verification_token = None

    if settings.email_enabled:
        ip = _get_client_ip(request)
        if not await _check_rate_limit(
            f"email_send:{ip}", EMAIL_SEND_MAX_PER_IP, EMAIL_SEND_WINDOW
        ):
            raise HTTPException(status_code=429, detail="Too many requests")

        from app.services.email_service import send_verification_email

        await send_verification_email(db, user)

    await db.commit()
    return {"message": "Email updated. Please check your inbox for verification."}


@router.post("/email/verify")
async def resend_verification(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """確認メールを再送する。5分に1回のレート制限あり。"""
    if not settings.email_enabled:
        raise HTTPException(status_code=422, detail="Email is not configured on this server")

    if user.email_verified:
        return {"message": "Email already verified"}

    ip = _get_client_ip(request)
    if not await _check_rate_limit(
        f"email_send:{ip}", EMAIL_SEND_MAX_PER_IP, EMAIL_SEND_WINDOW
    ):
        raise HTTPException(status_code=429, detail="Too many requests")

    from app.services.email_service import send_verification_email

    sent = await send_verification_email(db, user)
    if not sent:
        raise HTTPException(status_code=429, detail="Please wait before requesting again")
    await db.commit()
    return {"message": "Verification email sent"}


@router.post("/email/confirm")
async def confirm_email(
    body: ConfirmEmailRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """トークンでメールを確認する。認証不要。"""
    ip = _get_client_ip(request)
    if not await _check_rate_limit(
        f"email_confirm:{ip}", TOKEN_VERIFY_MAX_ATTEMPTS, TOKEN_VERIFY_WINDOW
    ):
        raise HTTPException(status_code=429, detail="Too many attempts")

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
    """パスワードリセットメールを送信する。メールの存在を漏洩させないため常に200を返す。"""
    if not settings.email_enabled:
        raise HTTPException(status_code=422, detail="Email is not configured on this server")

    # IPベースのレート制限（エンドポイントレベル）
    ip = _get_client_ip(request)
    if not await _check_rate_limit(f"forgot_password:{ip}", 5, 300):
        # 情報漏洩防止のため200を返す
        return {"message": "If an account with that email exists, a reset link has been sent"}

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user:
        # IPベースのメール送信レート制限（エンドポイント横断）
        if not await _check_rate_limit(
            f"email_send:{ip}", EMAIL_SEND_MAX_PER_IP, EMAIL_SEND_WINDOW
        ):
            # 情報漏洩防止のため200を返す
            return {
                "message": "If an account with that email exists, a reset link has been sent"
            }

        from app.services.email_service import send_password_reset_email

        await send_password_reset_email(db, user)
        await db.commit()

    return {"message": "If an account with that email exists, a reset link has been sent"}


@router.post("/auth/reset-password")
async def reset_password(
    body: ResetPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """トークンでパスワードをリセットする。"""
    ip = _get_client_ip(request)
    if not await _check_rate_limit(
        f"reset_password:{ip}", TOKEN_VERIFY_MAX_ATTEMPTS, TOKEN_VERIFY_WINDOW
    ):
        raise HTTPException(status_code=429, detail="Too many attempts")

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
