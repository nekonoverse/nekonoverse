"""Web Push notification service: VAPID key management, subscription CRUD, push delivery."""

import base64
import hashlib
import hmac
import json
import logging
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.push_subscription import PushSubscription

logger = logging.getLogger(__name__)

# DB保存されたVAPID鍵のインメモリキャッシュ
_cached_db_vapid_key: str | None = None


def set_db_vapid_key(key: str) -> None:
    """Set the DB-stored VAPID key in memory cache (called from admin endpoint)."""
    global _cached_db_vapid_key
    _cached_db_vapid_key = key


async def load_db_vapid_key_async(db: AsyncSession) -> None:
    """Load VAPID private key from DB into memory cache (called on startup)."""
    global _cached_db_vapid_key
    from app.services.server_settings_service import get_setting

    key = await get_setting(db, "vapid_private_key")
    if key:
        _cached_db_vapid_key = key


# 通知種別 → alertsキーのマッピング
NOTIFICATION_TYPE_TO_ALERT = {
    "mention": "mention",
    "reply": "mention",
    "follow": "follow",
    "reaction": "favourite",
    "favourite": "favourite",
    "renote": "reblog",
    "reblog": "reblog",
    "poll": "poll",
}


def _get_vapid_private_key_bytes() -> bytes:
    """Get VAPID private key as raw 32 bytes.

    Priority: DB setting (in-memory cache) > VAPID_PRIVATE_KEY env var > derived from SECRET_KEY.
    """
    # 1. インメモリキャッシュ (管理画面で生成された鍵、起動時にDBからロード)
    if _cached_db_vapid_key:
        return base64.urlsafe_b64decode(_cached_db_vapid_key + "==")

    # 2. 環境変数
    if settings.vapid_private_key:
        return base64.urlsafe_b64decode(settings.vapid_private_key + "==")

    # 3. SECRET_KEYからHKDFで決定論的に導出 (開発用フォールバック)
    derived = hmac.new(
        settings.secret_key.encode(), b"vapid-private-key", hashlib.sha256
    ).digest()
    return derived


def _private_key_to_ec():
    """Convert raw 32-byte private key to cryptography EC private key object."""
    from cryptography.hazmat.primitives.asymmetric import ec

    raw = _get_vapid_private_key_bytes()
    return ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())


def get_vapid_public_key_base64url() -> str:
    """Get VAPID public key as base64url-encoded string (for client subscription)."""
    ec_key = _private_key_to_ec()
    pub_numbers = ec_key.public_key().public_numbers()
    # Uncompressed point format: 0x04 + x (32 bytes) + y (32 bytes)
    x_bytes = pub_numbers.x.to_bytes(32, "big")
    y_bytes = pub_numbers.y.to_bytes(32, "big")
    raw_public = b"\x04" + x_bytes + y_bytes
    return base64.urlsafe_b64encode(raw_public).rstrip(b"=").decode()


def _get_vapid_claims() -> dict:
    """Build VAPID claims for pywebpush."""
    return {
        "sub": f"mailto:admin@{settings.domain}",
    }


def _get_vapid_private_key_pem() -> str:
    """Get VAPID private key as PEM string for pywebpush."""
    from cryptography.hazmat.primitives import serialization

    ec_key = _private_key_to_ec()
    return ec_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


# --- Subscription CRUD ---


async def get_subscription_by_session(
    db: AsyncSession, session_id: str
) -> PushSubscription | None:
    result = await db.execute(
        select(PushSubscription).where(PushSubscription.session_id == session_id)
    )
    return result.scalar_one_or_none()


async def create_subscription(
    db: AsyncSession,
    actor_id: uuid.UUID,
    session_id: str,
    endpoint: str,
    key_p256dh: str,
    key_auth: str,
    alerts: dict | None = None,
    policy: str = "all",
) -> PushSubscription:
    """Create or replace push subscription for a session."""
    # セッションにつき1購読 — 既存があれば削除
    await db.execute(
        delete(PushSubscription).where(PushSubscription.session_id == session_id)
    )

    default_alerts = {
        "mention": True,
        "follow": True,
        "favourite": True,
        "reblog": True,
        "poll": True,
    }
    if alerts:
        default_alerts.update(alerts)

    sub = PushSubscription(
        actor_id=actor_id,
        session_id=session_id,
        endpoint=endpoint,
        key_p256dh=key_p256dh,
        key_auth=key_auth,
        alerts=default_alerts,
        policy=policy,
    )
    db.add(sub)
    await db.flush()
    return sub


async def update_subscription_alerts(
    db: AsyncSession,
    session_id: str,
    alerts: dict | None = None,
    policy: str | None = None,
) -> PushSubscription | None:
    sub = await get_subscription_by_session(db, session_id)
    if not sub:
        return None

    if alerts:
        merged = dict(sub.alerts)
        merged.update(alerts)
        sub.alerts = merged
    if policy is not None:
        sub.policy = policy
    await db.flush()
    return sub


async def delete_subscription(db: AsyncSession, session_id: str) -> bool:
    result = await db.execute(
        delete(PushSubscription).where(PushSubscription.session_id == session_id)
    )
    return result.rowcount > 0


async def get_subscriptions_for_actor(
    db: AsyncSession, actor_id: uuid.UUID
) -> list[PushSubscription]:
    result = await db.execute(
        select(PushSubscription).where(PushSubscription.actor_id == actor_id)
    )
    return list(result.scalars().all())


# --- Push delivery ---


async def is_push_enabled(db: AsyncSession) -> bool:
    """Check if push notifications are enabled server-wide."""
    from app.services.server_settings_service import get_setting

    val = await get_setting(db, "push_enabled")
    return val != "false"


async def send_web_push(
    db: AsyncSession,
    recipient_id: uuid.UUID,
    notification_type: str,
    sender_display_name: str | None = None,
    body: str | None = None,
    notification_id: str | None = None,
    sender_id: uuid.UUID | None = None,
) -> None:
    """Send Web Push to all subscriptions for a recipient, filtered by alert settings."""
    # サーバー全体でプッシュ通知が無効な場合はスキップ
    if not await is_push_enabled(db):
        return

    alert_key = NOTIFICATION_TYPE_TO_ALERT.get(notification_type)
    if not alert_key:
        return

    subs = await get_subscriptions_for_actor(db, recipient_id)
    if not subs:
        return

    # policyフィルタ用: 送信者とのフォロー関係を事前取得
    follow_status: dict[str, bool] | None = None
    if sender_id:
        follow_status = await _get_follow_status(db, recipient_id, sender_id)

    from pywebpush import WebPushException, webpush

    vapid_private_key_pem = _get_vapid_private_key_pem()
    vapid_claims = _get_vapid_claims()

    payload = json.dumps({
        "notification_id": notification_id or "",
        "notification_type": notification_type,
        "title": _build_title(notification_type, sender_display_name),
        "body": body or "",
    })

    stale_ids: list[uuid.UUID] = []

    for sub in subs:
        # alertsフィルタ
        if not sub.alerts.get(alert_key, False):
            continue

        # policyフィルタ
        if not _passes_policy(sub.policy, follow_status):
            continue

        subscription_info = {
            "endpoint": sub.endpoint,
            "keys": {
                "p256dh": sub.key_p256dh,
                "auth": sub.key_auth,
            },
        }

        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=vapid_private_key_pem,
                vapid_claims=vapid_claims,
            )
        except WebPushException as e:
            # 410 Gone = 購読が無効 → 自動削除
            if hasattr(e, "response") and e.response is not None and e.response.status_code == 410:
                stale_ids.append(sub.id)
            else:
                logger.warning("Web Push failed for %s: %s", sub.endpoint, e)
        except Exception as e:
            logger.warning("Web Push unexpected error for %s: %s", sub.endpoint, e)

    # 無効な購読を一括削除
    if stale_ids:
        await db.execute(
            delete(PushSubscription).where(PushSubscription.id.in_(stale_ids))
        )
        await db.flush()


def _build_title(notification_type: str, sender_name: str | None) -> str:
    name = sender_name or "Someone"
    titles = {
        "mention": f"{name} mentioned you",
        "reply": f"{name} replied to you",
        "follow": f"{name} followed you",
        "reaction": f"{name} reacted to your post",
        "favourite": f"{name} favourited your post",
        "renote": f"{name} boosted your post",
        "reblog": f"{name} boosted your post",
        "poll": "A poll has ended",
    }
    return titles.get(notification_type, "New notification")


async def _get_follow_status(
    db: AsyncSession, recipient_id: uuid.UUID, sender_id: uuid.UUID
) -> dict[str, bool]:
    """Check mutual follow status between recipient and sender."""
    from app.models.follow import Follow

    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == recipient_id, Follow.following_id == sender_id
        )
    )
    recipient_follows_sender = result.scalar_one_or_none() is not None

    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == sender_id, Follow.following_id == recipient_id
        )
    )
    sender_follows_recipient = result.scalar_one_or_none() is not None

    return {
        "followed": recipient_follows_sender,
        "follower": sender_follows_recipient,
    }


def _passes_policy(policy: str, follow_status: dict[str, bool] | None) -> bool:
    if policy == "all":
        return True
    if policy == "none":
        return False
    if not follow_status:
        return policy == "all"
    if policy == "followed":
        return follow_status.get("followed", False)
    if policy == "follower":
        return follow_status.get("follower", False)
    return True
