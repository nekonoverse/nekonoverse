"""サーバーリストAPI への定期通知ワーカー。

server_listing_enabled が有効な場合、1時間ごとにサーバー情報を
指定されたサーバーリストAPIへPOSTで通知する。
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select

from app.valkey_client import valkey as valkey_client

logger = logging.getLogger(__name__)

NOTIFY_INTERVAL = 3600  # 1時間
HEARTBEAT_KEY = "worker:server_listing:heartbeat"
REQUEST_TIMEOUT = 30


async def _collect_server_info(db) -> dict:
    """通知用のサーバー情報を収集する。"""
    from app import VERSION
    from app.config import settings as app_settings
    from app.models.actor import Actor
    from app.models.note import Note
    from app.models.user import User
    from app.services.server_settings_service import get_setting

    server_name = await get_setting(db, "server_name") or "Nekonoverse"
    server_description = await get_setting(db, "server_description") or ""
    registration_mode = await get_setting(db, "registration_mode") or "open"
    listing_enabled = (await get_setting(db, "server_listing_enabled") or "false") == "true"

    # ローカルユーザー数
    user_count_result = await db.execute(
        select(func.count()).select_from(Actor).where(Actor.domain.is_(None))
    )
    user_count = user_count_result.scalar() or 0

    # 月間アクティブユーザー数
    now = datetime.now(timezone.utc)
    local_actor_ids = select(Actor.id).where(Actor.domain.is_(None))
    active_month_result = await db.execute(
        select(func.count(func.distinct(Note.actor_id))).where(
            Note.local.is_(True),
            Note.actor_id.in_(local_actor_ids),
            Note.published >= now - timedelta(days=30),
            Note.deleted_at.is_(None),
        )
    )
    active_month = active_month_result.scalar() or 0

    # 管理者名: 最初のadminユーザー
    admin_result = await db.execute(
        select(User).where(User.role == "admin").order_by(User.created_at.asc()).limit(1)
    )
    admin_user = admin_result.scalar_one_or_none()
    admin_name = ""
    if admin_user and admin_user.actor:
        admin_name = admin_user.actor.display_name or admin_user.actor.username

    return {
        "name": server_name,
        "url": app_settings.server_url,
        "version": VERSION,
        "admin_name": admin_name,
        "description": server_description,
        "registration_mode": registration_mode,
        "listing_enabled": listing_enabled,
        "user_count": user_count,
        "active_month": active_month,
    }


async def _notify_listing_api(listing_url: str, payload: dict) -> None:
    """サーバーリストAPIへPOSTで通知する。"""
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        resp = await client.post(listing_url, json=payload)
        resp.raise_for_status()
    logger.info("Server listing notification sent to %s (status=%d)", listing_url, resp.status_code)


async def run_server_listing_loop() -> None:
    """サーバーリストAPI への定期通知ループ。"""
    logger.info("Server listing worker started (interval=%ds)", NOTIFY_INTERVAL)

    while True:
        try:
            await valkey_client.set(HEARTBEAT_KEY, "alive", ex=NOTIFY_INTERVAL * 3)

            from app.database import async_session
            from app.services.server_settings_service import get_setting

            async with async_session() as db:
                listing_url = await get_setting(db, "server_listing_url")

                if not listing_url:
                    logger.debug("Server listing URL not configured, skipping")
                else:
                    payload = await _collect_server_info(db)
                    await _notify_listing_api(listing_url, payload)
        except Exception:
            logger.exception("Error in server listing notification loop")

        await asyncio.sleep(NOTIFY_INTERVAL)
