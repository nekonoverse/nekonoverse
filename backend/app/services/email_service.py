"""メールサービス: SMTP送信、テンプレート、トークン管理。"""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from uuid import UUID

import aiosmtplib
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User

logger = logging.getLogger(__name__)

VERIFICATION_TOKEN_EXPIRY = timedelta(hours=24)
RESET_TOKEN_EXPIRY = timedelta(hours=1)
RESEND_COOLDOWN = timedelta(minutes=5)


async def send_email(to: str, subject: str, html: str, text: str) -> None:
    """SMTP経由でメールを送信する。メールキューワーカーから呼び出される。"""
    if not settings.email_enabled:
        logger.warning("Email not configured, skipping send to %s", to)
        return

    msg = MIMEMultipart("alternative")
    msg["From"] = settings.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    use_tls = settings.smtp_security == "ssl"
    start_tls = settings.smtp_security == "starttls"

    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user,
        password=settings.smtp_password,
        use_tls=use_tls,
        start_tls=start_tls,
    )


def _base_html(title: str, body: str) -> str:
    """メール本文を最小限のHTMLテンプレートでラップする。"""
    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{title}</title></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
             max-width: 600px; margin: 0 auto; padding: 20px; color: #333;">
  <div style="border-bottom: 2px solid #6364ff; padding-bottom: 10px; margin-bottom: 20px;">
    <h2 style="margin: 0; color: #6364ff;">{settings.domain}</h2>
  </div>
  {body}
  <div style="margin-top: 30px; padding-top: 15px; border-top: 1px solid #eee;
              font-size: 12px; color: #999;">
    This email was sent from {settings.domain}. If you did not request this, please ignore it.
  </div>
</body>
</html>"""


def render_verification_email(username: str, verify_url: str) -> tuple[str, str]:
    """メール確認用メールをレンダリングする。(html, text) を返す。"""
    html_body = f"""\
  <p>Hello <strong>{username}</strong>,</p>
  <p>Please verify your email address by clicking the button below:</p>
  <p style="text-align: center; margin: 30px 0;">
    <a href="{verify_url}"
       style="background: #6364ff; color: white; padding: 12px 30px;
              border-radius: 6px; text-decoration: none; font-weight: bold;">
      Verify Email
    </a>
  </p>
  <p style="font-size: 13px; color: #666;">
    Or copy and paste this URL into your browser:<br>
    <a href="{verify_url}" style="color: #6364ff;">{verify_url}</a>
  </p>
  <p style="font-size: 13px; color: #666;">This link expires in 24 hours.</p>"""

    text = (
        f"Hello {username},\n\n"
        f"Please verify your email address by visiting:\n{verify_url}\n\n"
        f"This link expires in 24 hours.\n"
    )
    return _base_html("Verify your email", html_body), text


def render_password_reset_email(username: str, reset_url: str) -> tuple[str, str]:
    """パスワードリセット用メールをレンダリングする。(html, text) を返す。"""
    html_body = f"""\
  <p>Hello <strong>{username}</strong>,</p>
  <p>A password reset was requested for your account. \
Click the button below to set a new password:</p>
  <p style="text-align: center; margin: 30px 0;">
    <a href="{reset_url}"
       style="background: #6364ff; color: white; padding: 12px 30px;
              border-radius: 6px; text-decoration: none; font-weight: bold;">
      Reset Password
    </a>
  </p>
  <p style="font-size: 13px; color: #666;">
    Or copy and paste this URL into your browser:<br>
    <a href="{reset_url}" style="color: #6364ff;">{reset_url}</a>
  </p>
  <p style="font-size: 13px; color: #666;">
    This link expires in 1 hour. If you did not request this, you can safely ignore this email.
  </p>"""

    text = (
        f"Hello {username},\n\n"
        f"A password reset was requested for your account.\n"
        f"Visit this URL to set a new password:\n{reset_url}\n\n"
        f"This link expires in 1 hour.\n"
        f"If you did not request this, you can safely ignore this email.\n"
    )
    return _base_html("Reset your password", html_body), text


async def send_verification_email(db: AsyncSession, user: User) -> bool:
    """トークンを生成し、確認メールをキューに追加する。クールダウン中はFalseを返す。"""
    if not settings.email_enabled:
        return False

    now = datetime.now(timezone.utc)
    if (
        user.email_verification_sent_at
        and now - user.email_verification_sent_at < RESEND_COOLDOWN
    ):
        return False

    token = secrets.token_urlsafe(32)
    user.email_verification_token = token
    user.email_verification_sent_at = now
    await db.flush()

    verify_url = f"{settings.frontend_url}/verify-email?token={token}&uid={user.id}"
    username = user.actor.username if user.actor else "User"
    html, text = render_verification_email(username, verify_url)

    from app.services.email_queue import enqueue_email

    await enqueue_email(user.email, "Verify your email address", html, text)
    return True


async def send_password_reset_email(db: AsyncSession, user: User) -> bool:
    """トークンを生成し、パスワードリセットメールをキューに追加する。クールダウン中はFalseを返す。"""
    if not settings.email_enabled:
        return False

    now = datetime.now(timezone.utc)
    if user.password_reset_sent_at and now - user.password_reset_sent_at < RESEND_COOLDOWN:
        return False

    token = secrets.token_urlsafe(32)
    user.password_reset_token = token
    user.password_reset_sent_at = now
    await db.flush()

    reset_url = f"{settings.frontend_url}/reset-password?token={token}&uid={user.id}"
    username = user.actor.username if user.actor else "User"
    html, text = render_password_reset_email(username, reset_url)

    from app.services.email_queue import enqueue_email

    await enqueue_email(user.email, "Reset your password", html, text)
    return True


async def verify_email_token(db: AsyncSession, user_id: UUID, token: str) -> bool:
    """メールトークンを検証する。成功時にTrueを返す。"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.email_verification_token:
        return False

    if not secrets.compare_digest(user.email_verification_token, token):
        return False

    if user.email_verification_sent_at:
        now = datetime.now(timezone.utc)
        if now - user.email_verification_sent_at > VERIFICATION_TOKEN_EXPIRY:
            return False

    user.email_verified = True
    user.email_verification_token = None
    await db.flush()
    return True


async def verify_reset_token(db: AsyncSession, user_id: UUID, token: str) -> User | None:
    """パスワードリセットトークンを検証する。成功時にUserを返し、失敗時にNoneを返す。"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.password_reset_token:
        return None

    if not secrets.compare_digest(user.password_reset_token, token):
        return None

    if user.password_reset_sent_at:
        now = datetime.now(timezone.utc)
        if now - user.password_reset_sent_at > RESET_TOKEN_EXPIRY:
            return None

    return user
