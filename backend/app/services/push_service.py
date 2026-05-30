"""Web Push 通知サービス: VAPID鍵管理、購読CRUD、プッシュ配信。"""

import base64
import hashlib
import hmac
import json
import logging
import uuid
from urllib.parse import urlsplit

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.push_subscription import PushSubscription

logger = logging.getLogger(__name__)

# DB保存されたVAPID鍵のインメモリキャッシュ
_cached_db_vapid_key: str | None = None


def set_db_vapid_key(key: str) -> None:
    """DB保存されたVAPID鍵をインメモリキャッシュに設定する (管理エンドポイントから呼出)。"""
    global _cached_db_vapid_key
    _cached_db_vapid_key = key


async def load_db_vapid_key_async(db: AsyncSession) -> None:
    """VAPID秘密鍵をDBからインメモリキャッシュに読み込む (起動時に呼出)。"""
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
    """VAPID秘密鍵を生の32バイトとして取得する。

    優先順位: DB設定 (インメモリキャッシュ) > VAPID_PRIVATE_KEY 環境変数 > SECRET_KEY から導出。
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
    """生の32バイト秘密鍵を cryptography EC 秘密鍵オブジェクトに変換する。"""
    from cryptography.hazmat.primitives.asymmetric import ec

    raw = _get_vapid_private_key_bytes()
    return ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())


def get_vapid_public_key_base64url() -> str:
    """VAPID公開鍵をbase64urlエンコード文字列で取得する (クライアント購読用)。"""
    ec_key = _private_key_to_ec()
    pub_numbers = ec_key.public_key().public_numbers()
    # 非圧縮ポイント形式: 0x04 + x (32バイト) + y (32バイト)
    x_bytes = pub_numbers.x.to_bytes(32, "big")
    y_bytes = pub_numbers.y.to_bytes(32, "big")
    raw_public = b"\x04" + x_bytes + y_bytes
    return base64.urlsafe_b64encode(raw_public).rstrip(b"=").decode()


def _get_vapid_claims() -> dict:
    """pywebpush 用の VAPID claims を構築する。"""
    return {
        "sub": f"mailto:admin@{settings.domain}",
    }


def _get_vapid_private_key_base64url() -> str:
    """pywebpush 用に VAPID 秘密鍵を base64url(raw 32 バイト) で取得する。

    pywebpush (py_vapid) の Vapid.from_string() は引数を base64url decode し、
    長さが 32 バイトなら from_raw()、そうでなければ from_der() を試みる。
    PEM 文字列を渡すと from_der() に落ちて ASN.1 parse error になるため、
    必ず raw 鍵の base64url 形式 (=43 文字) を渡す。
    """
    raw = _get_vapid_private_key_bytes()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


# --- 購読 CRUD ---


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
    """セッションのプッシュ購読を作成または置換する。"""
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


# --- プッシュ配信 ---


async def is_push_enabled(db: AsyncSession) -> bool:
    """サーバー全体でプッシュ通知が有効か確認する。"""
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
    """受信者の全購読にアラート設定でフィルタリングしてWeb Pushを送信する。"""
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

    vapid_private_key = _get_vapid_private_key_base64url()
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
                vapid_private_key=vapid_private_key,
                vapid_claims=vapid_claims,
            )
        except WebPushException as e:
            response = getattr(e, "response", None)
            status = getattr(response, "status_code", None) if response is not None else None

            # 410 Gone = 購読が無効 → 自動削除
            if status == 410:
                stale_ids.append(sub.id)
                continue

            # 4xx/5xx の応答本文はプッシュサービス (Apple/Mozilla/FCM) の
            # 具体的な拒否理由を含む。推測ベースのデバッグを避けるため
            # status と本文の先頭をログに残す。
            _log_web_push_failure(sub.endpoint, response, e)
        except Exception as e:
            # pywebpush 外の予期せぬ例外は本 PR の観測強化対象外だが、
            # スタックトレースが無いと後から追えないので exc_info も残す
            logger.warning(
                "Web Push unexpected error: host=%s error=%s",
                _endpoint_host(sub.endpoint),
                e,
                exc_info=True,
            )

    # 無効な購読を一括削除
    if stale_ids:
        await db.execute(
            delete(PushSubscription).where(PushSubscription.id.in_(stale_ids))
        )
        await db.flush()


def _endpoint_host(endpoint: str) -> str:
    """endpoint URL からホスト部分のみを取り出す (ログでの PII / 検索性配慮)。"""
    try:
        return urlsplit(endpoint).hostname or endpoint
    except ValueError:
        return endpoint


def _log_web_push_failure(
    endpoint: str, response: object | None, error: Exception
) -> None:
    """WebPushException 発生時にプッシュサービスからの応答本文を含めてログする。

    Apple (web.push.apple.com) などは status だけでなく本文に具体的な拒否理由を
    返す。response が取れない場合は例外メッセージで代替する。
    """
    host = _endpoint_host(endpoint)
    if response is None:
        logger.warning("Web Push failed: host=%s error=%s", host, error)
        return

    status = getattr(response, "status_code", None)
    body_excerpt = ""
    try:
        text = getattr(response, "text", None)
        if text:
            body_excerpt = text[:500]
    except Exception:
        # 「なぜ body が unavailable だったか」を後から追えるよう原因も残す
        logger.debug("Failed to read Web Push response body", exc_info=True)
        body_excerpt = "<unavailable>"
    logger.warning(
        "Web Push failed: host=%s status=%s body=%s",
        host,
        status,
        body_excerpt,
    )


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
    """受信者と送信者の相互フォロー状態を確認する。"""
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
