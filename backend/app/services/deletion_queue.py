"""アカウント削除の猶予期間チェック用ワーカーループ。

1時間ごとに deletion_scheduled_at が経過したアカウントを検出し、
execute_deletion を実行する。
"""

import asyncio
import logging

from app.valkey_client import valkey as valkey_client

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 3600  # 1時間
HEARTBEAT_KEY = "worker:deletion:heartbeat"


async def run_deletion_check_loop() -> None:
    """削除予約の猶予期間が経過したアカウントを定期チェックする。"""
    logger.info("Deletion check worker started (interval=%ds)", CHECK_INTERVAL)

    while True:
        try:
            await valkey_client.set(HEARTBEAT_KEY, "alive", ex=CHECK_INTERVAL * 3)

            from app.database import async_session
            from app.services.account_deletion_service import process_expired_deletions

            async with async_session() as db:
                count = await process_expired_deletions(db)
                if count:
                    logger.info("Processed %d expired account deletion(s)", count)
        except Exception:
            logger.exception("Error in deletion check loop")

        await asyncio.sleep(CHECK_INTERVAL)
