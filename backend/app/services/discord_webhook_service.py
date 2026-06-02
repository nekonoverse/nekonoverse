"""Discord 互換 Webhook 通知サービス。

ユーザーごとに登録された Webhook URL に対して、通知タイプ別フィルタを通して
embeds 形式の payload を POST する。create_notification() からフックされる。
"""

import asyncio
import html
import ipaddress
import logging
import re
import socket
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.models.actor import Actor
from app.models.discord_webhook import DiscordWebhook
from app.models.note import Note
from app.models.notification import Notification
from app.models.user import User
from app.utils.http_client import make_async_client

logger = logging.getLogger(__name__)

# 連続失敗で自動的に enabled=False にする閾値
AUTO_DISABLE_THRESHOLD = 5

# Discord embed タイトル/description の最大長 (Discord API 仕様)
DISCORD_TITLE_LIMIT = 256
DISCORD_DESCRIPTION_LIMIT = 4000

# HTTP retry の試行回数と backoff (秒)。429 は Retry-After を尊重し、それ以外で
# 5xx/接続失敗の暫定 backoff として使う。
RETRY_DELAYS = [0.5, 1.0, 2.0]

# 429 で Retry-After を尊重するときの上限秒数 (悪意ある攻撃者が大きな値を
# 返してきても DoS にならないように)。
MAX_RETRY_AFTER_SECONDS = 30.0

# fire-and-forget 配送タスクの強参照保持 (GC 防止)
_outstanding_tasks: set[asyncio.Task] = set()

# 通知タイプ別の embed 色 (Discord API は 0xRRGGBB 形式の整数)
NOTIFICATION_COLORS = {
    "mention": 0x4C8AF0,        # blue
    "reply": 0x4C8AF0,
    "direct": 0x9B59B6,         # purple (mention の direct visibility 派生)
    "quote": 0x1ABC9C,          # teal
    "reaction": 0xF39C12,       # orange
    "renote": 0x2ECC71,         # green
    "follow": 0xE91E63,         # pink
    "follow_request": 0xE91E63,
}

# 通知タイプ別の表示文言 (日本語)。Discord embed タイトルに使う
NOTIFICATION_ACTIONS = {
    "mention": "がメンションしました",
    "reply": "が返信しました",
    "direct": "がダイレクトメッセージを送りました",
    "quote": "が引用しました",
    "reaction": "がリアクションしました",
    "renote": "がリノートしました",
    "follow": "にフォローされました",
    "follow_request": "がフォローリクエストを送りました",
}


def _select_notify_column(notification_type: str, note_visibility: str | None) -> str | None:
    """通知タイプ (+ note visibility) から、どの notify_* カラムを参照するか決める。

    - mention で visibility=direct → notify_direct
    - mention/reply → notify_mention (reply は mention の派生として統合)
    - その他は notification_type と同名カラム

    対応するカラムがなければ None を返す (Webhook 配送をスキップ)。
    """
    if notification_type in ("mention", "reply"):
        if note_visibility == "direct":
            return "notify_direct"
        return "notify_mention"
    if notification_type == "quote":
        return "notify_quote"
    if notification_type == "reaction":
        return "notify_reaction"
    if notification_type == "renote":
        return "notify_renote"
    if notification_type == "follow":
        return "notify_follow"
    if notification_type == "follow_request":
        return "notify_follow_request"
    return None


def _resolve_event_kind(notification_type: str, note_visibility: str | None) -> str:
    """色とタイトル文言の選択用に、direct を派生イベントとして扱うキーを返す。"""
    if notification_type in ("mention", "reply") and note_visibility == "direct":
        return "direct"
    return notification_type


def mask_webhook_url(url: str) -> str:
    """Webhook URL の末尾トークンを伏せ字にする。

    Discord 形式 `https://discord.com/api/webhooks/{id}/{token}` を想定。
    パスの最後のセグメントを完全マスクし、末尾 4 文字だけ残す。
    """
    if "/" in url:
        head, sep, tail = url.rpartition("/")
        if tail and len(tail) >= 4:
            return f"{head}{sep}***{tail[-4:]}"
    if len(url) > 8:
        return "***" + url[-4:]
    return "***"


def _strip_html(html_text: str) -> str:
    """HTML タグを荒く除去してプレーンテキスト化する。

    Discord embed description 用の最小限の整形。完全な sanitize ではなく、
    タグ除去 + エンティティデコード + 連続空白の正規化のみ行う。
    """
    text = re.sub(r"<br\s*/?>", "\n", html_text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def is_safe_webhook_target(url: str) -> bool:
    """Webhook URL の宛先が外部公開 IP に解決されることを確認する (SSRF 対策)。

    以下のいずれかなら False を返す:
    - スキームが http/https ではない
    - ホスト名が空、または `.local` で終わる (mDNS)
    - DNS 解決した IP のいずれかが private / loopback / link-local /
      multicast / reserved / unspecified
    - DNS 解決そのものが失敗
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    if not host:
        return False
    if host.endswith(".local"):
        return False

    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    if not infos:
        return False

    for _family, _socktype, _proto, _canonname, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
    return True


def _build_embed(
    notification: Notification,
    sender: Actor | None,
    note: Note | None,
) -> dict:
    """Discord embed payload を組み立てる。"""
    note_visibility = note.visibility if note else None
    event_kind = _resolve_event_kind(notification.type, note_visibility)

    sender_name = "Someone"
    if sender:
        sender_name = sender.display_name or sender.username or sender_name

    action = NOTIFICATION_ACTIONS.get(event_kind, "が通知を送りました")
    title = f"{sender_name} さん{action}"
    if notification.type == "reaction" and notification.reaction_emoji:
        title = f"{title} ({notification.reaction_emoji})"
    if len(title) > DISCORD_TITLE_LIMIT:
        title = title[: DISCORD_TITLE_LIMIT - 1] + "…"

    description: str | None = None
    url: str | None = None
    if note is not None:
        if note.content:
            description = _strip_html(note.content)
            if len(description) > DISCORD_DESCRIPTION_LIMIT:
                description = description[: DISCORD_DESCRIPTION_LIMIT - 1] + "…"
        url = f"{settings.frontend_url.rstrip('/')}/notes/{note.id}"

    embed: dict = {
        "title": title,
        "color": NOTIFICATION_COLORS.get(event_kind, 0x95A5A6),
        "timestamp": notification.created_at.astimezone(timezone.utc).isoformat(),
    }
    if description:
        embed["description"] = description
    if url:
        embed["url"] = url
    if sender:
        author: dict = {"name": sender.username or sender_name}
        if sender.avatar_url:
            author["icon_url"] = sender.avatar_url
        if sender.ap_id:
            author["url"] = sender.ap_id
        embed["author"] = author

    # note 本文中の @everyone / @here / ロール ID が Discord 側で展開されないよう抑止
    return {
        "username": "Nekonoverse",
        "embeds": [embed],
        "allowed_mentions": {"parse": []},
    }


DeliveryOutcome = str  # "success" | "failed" | "rate_limited"


async def _post_with_retry(
    url: str, payload: dict
) -> tuple[DeliveryOutcome, int | None, str | None]:
    """POST を最大 3 回リトライする。

    Returns:
        (outcome, last_status_code, last_error_text)

    outcome:
        - "success"      : 2xx 応答
        - "failed"       : 永続的失敗 (4xx <非429>, 5xx 連続, ネットワーク失敗)
        - "rate_limited" : 全試行で 429 のみ。consecutive_failures は触らない
    """
    last_status: int | None = None
    last_error: str | None = None
    saw_only_rate_limit = True
    async with make_async_client(timeout=10.0) as client:
        attempts = len(RETRY_DELAYS)
        for attempt in range(attempts):
            try:
                response = await client.post(url, json=payload)
            except Exception as exc:
                last_status = None
                last_error = f"{type(exc).__name__}: {exc}"[:500]
                saw_only_rate_limit = False
            else:
                last_status = response.status_code
                if 200 <= response.status_code < 300:
                    return "success", last_status, None
                if response.status_code == 429:
                    # rate limited — Retry-After を尊重して再試行 (auto-disable には数えない)
                    try:
                        retry_after = float(response.headers.get("Retry-After", "1"))
                    except ValueError:
                        retry_after = 1.0
                    retry_after = min(max(retry_after, 0.0), MAX_RETRY_AFTER_SECONDS)
                    last_error = "rate limited"
                    if attempt < attempts - 1:
                        await asyncio.sleep(retry_after)
                        continue
                    # 全試行 429 のときだけ rate_limited 扱いにする。
                    # 5xx 混在のあと 429 で終わったケースは失敗とみなす
                    # (Discord が過負荷時にステータスを切り替えるパターンでも
                    # 失敗カウンタが進む方が安全寄り)
                    if saw_only_rate_limit:
                        return "rate_limited", last_status, "rate limited"
                    return "failed", last_status, last_error
                # 429 以外の 4xx は永続失敗として即時終了
                if 400 <= response.status_code < 500:
                    last_error = (response.text or "")[:500]
                    return "failed", last_status, last_error
                # 5xx — リトライ対象
                last_error = (response.text or "")[:500]
                saw_only_rate_limit = False
            if attempt < attempts - 1:
                await asyncio.sleep(RETRY_DELAYS[attempt])
    if saw_only_rate_limit and last_status == 429:
        return "rate_limited", last_status, last_error
    return "failed", last_status, last_error


async def _record_result(
    webhook_id: uuid.UUID,
    outcome: DeliveryOutcome,
    error: str | None,
) -> None:
    """配送結果を別セッションで DB に書き戻す。

    別セッションにする理由: 元の create_notification() の Transaction が
    commit/rollback されるタイミングと独立して保存したいため。
    consecutive_failures は原子的に SQL でインクリメントしロストアップデートを防ぐ。
    """
    try:
        async with async_session() as session:
            if outcome == "rate_limited":
                # auto-disable には数えないが last_error は記録する
                await session.execute(
                    update(DiscordWebhook)
                    .where(DiscordWebhook.id == webhook_id)
                    .values(last_error=error)
                )
                await session.commit()
                return
            if outcome == "success":
                await session.execute(
                    update(DiscordWebhook)
                    .where(DiscordWebhook.id == webhook_id)
                    .values(
                        consecutive_failures=0,
                        last_error=None,
                        last_delivered_at=datetime.now(timezone.utc),
                    )
                )
                await session.commit()
                return
            # failed: 原子的にカウンタをインクリメント
            await session.execute(
                update(DiscordWebhook)
                .where(DiscordWebhook.id == webhook_id)
                .values(
                    consecutive_failures=DiscordWebhook.consecutive_failures + 1,
                    last_error=error,
                )
            )
            await session.commit()
            # 閾値超えで disable (別 UPDATE で原子的に判定)
            await session.execute(
                update(DiscordWebhook)
                .where(
                    DiscordWebhook.id == webhook_id,
                    DiscordWebhook.consecutive_failures >= AUTO_DISABLE_THRESHOLD,
                )
                .values(enabled=False)
            )
            await session.commit()
    except Exception:
        logger.exception("Failed to record discord webhook delivery result")


async def _deliver(webhook_id: uuid.UUID, url: str, payload: dict) -> None:
    """1 つの Webhook に対して配送 → 結果記録を行う。fire-and-forget で呼ばれる。"""
    if not await is_safe_webhook_target(url):
        logger.warning(
            "Discord webhook delivery rejected (unsafe target): webhook_id=%s",
            webhook_id,
        )
        await _record_result(webhook_id, "failed", "unsafe target")
        return
    outcome, _, error = await _post_with_retry(url, payload)
    if outcome != "success":
        logger.warning(
            "Discord webhook delivery %s: webhook_id=%s error=%s",
            outcome,
            webhook_id,
            error,
        )
    await _record_result(webhook_id, outcome, error)


def _spawn_delivery(webhook_id: uuid.UUID, url: str, payload: dict) -> asyncio.Task:
    """_deliver を fire-and-forget で投げ、強参照を保持して GC を防ぐ。"""
    task = asyncio.create_task(_deliver(webhook_id, url, payload))
    _outstanding_tasks.add(task)
    task.add_done_callback(_outstanding_tasks.discard)
    return task


async def dispatch_webhooks(
    db: AsyncSession,
    notification: Notification,
    sender: Actor | None,
    note: Note | None = None,
) -> None:
    """通知作成時に呼ばれる。該当ユーザーの全有効 Webhook を fire-and-forget で叩く。

    create_notification() の commit より先に呼ばれるため、DB クエリは row が
    まだ visible でない可能性がある。webhook 一覧の取得自体は recipient_id とは
    無関係なので問題ないが、配送結果の記録は別セッションで行う (_record_result)。
    """
    # recipient (actor_id) からそのユーザーを特定
    user_q = select(User).where(User.actor_id == notification.recipient_id)
    user = (await db.execute(user_q)).scalar_one_or_none()
    if user is None:
        # リモートアクター宛の通知などはここで弾かれる
        return

    note_visibility = note.visibility if note else None
    column_name = _select_notify_column(notification.type, note_visibility)
    if column_name is None:
        return

    webhooks_q = select(DiscordWebhook).where(
        DiscordWebhook.user_id == user.id,
        DiscordWebhook.enabled.is_(True),
    )
    webhooks = (await db.execute(webhooks_q)).scalars().all()
    if not webhooks:
        return

    payload = _build_embed(notification, sender, note)

    for webhook in webhooks:
        if not getattr(webhook, column_name):
            continue
        # fire-and-forget。Web Push と同じく失敗で通知作成を失敗させない
        _spawn_delivery(webhook.id, webhook.webhook_url, payload)


# ──────────────────────────────────────────────
# CRUD (API ハンドラから呼ばれる)
# ──────────────────────────────────────────────


async def list_webhooks(db: AsyncSession, user_id: uuid.UUID) -> list[DiscordWebhook]:
    result = await db.execute(
        select(DiscordWebhook)
        .where(DiscordWebhook.user_id == user_id)
        .order_by(DiscordWebhook.created_at.asc())
    )
    return list(result.scalars().all())


async def get_webhook(
    db: AsyncSession, user_id: uuid.UUID, webhook_id: uuid.UUID
) -> DiscordWebhook | None:
    result = await db.execute(
        select(DiscordWebhook).where(
            DiscordWebhook.id == webhook_id,
            DiscordWebhook.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def create_webhook(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    name: str,
    webhook_url: str,
    notify_mention: bool = True,
    notify_direct: bool = True,
    notify_quote: bool = True,
    notify_reaction: bool = True,
    notify_renote: bool = True,
    notify_follow: bool = True,
    notify_follow_request: bool = True,
    enabled: bool = True,
) -> DiscordWebhook:
    webhook = DiscordWebhook(
        user_id=user_id,
        name=name,
        webhook_url=webhook_url,
        notify_mention=notify_mention,
        notify_direct=notify_direct,
        notify_quote=notify_quote,
        notify_reaction=notify_reaction,
        notify_renote=notify_renote,
        notify_follow=notify_follow,
        notify_follow_request=notify_follow_request,
        enabled=enabled,
    )
    db.add(webhook)
    await db.flush()
    return webhook


async def update_webhook(
    db: AsyncSession, webhook: DiscordWebhook, updates: dict
) -> DiscordWebhook:
    for key, value in updates.items():
        if value is None:
            continue
        setattr(webhook, key, value)
    # URL を再設定した場合は失敗カウントをリセット
    if "webhook_url" in updates and updates["webhook_url"] is not None:
        webhook.consecutive_failures = 0
        webhook.last_error = None
    await db.flush()
    return webhook


async def delete_webhook(db: AsyncSession, webhook: DiscordWebhook) -> None:
    await db.delete(webhook)
    await db.flush()


async def send_test_payload(
    webhook: DiscordWebhook,
) -> tuple[bool, int | None, str | None]:
    """テスト送信。CRUD とは別に呼ばれ、結果を直接返す。

    成功/失敗を Webhook の状態 (consecutive_failures, last_error, last_delivered_at)
    にも反映する (別セッションで _record_result 経由)。
    """
    if not await is_safe_webhook_target(webhook.webhook_url):
        await _record_result(webhook.id, "failed", "unsafe target")
        return False, None, "unsafe target"

    payload = {
        "username": "Nekonoverse",
        "embeds": [
            {
                "title": "テスト通知",
                "description": (
                    "Nekonoverse からのテスト送信です。"
                    "この embed が見えれば Webhook 設定は正常です。"
                ),
                "color": 0x4C8AF0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ],
        "allowed_mentions": {"parse": []},
    }
    outcome, status, error = await _post_with_retry(webhook.webhook_url, payload)
    await _record_result(webhook.id, outcome, error)
    return outcome == "success", status, error
