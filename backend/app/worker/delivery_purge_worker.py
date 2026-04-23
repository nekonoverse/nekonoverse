"""delivered 済み配送ジョブの定期パージ。

delivery_queue テーブルは UPDATE-heavy なため、配送完了後の行を溜め込むと
bloat が進行して autovacuum 追従コストも上がる。1 時間ごとに 24 時間より古い
delivered ジョブを削除する。dead / pending には触らない（retry 用途で保持）。
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 3600  # 1 時間
PURGE_OLDER_THAN_HOURS = 24
HEARTBEAT_KEY = "worker:delivery_purge:heartbeat"


async def _run_once() -> int:
    """1 回分のパージ処理を実行する。テスト容易性のため切り出し。"""
    # lazy import でテスト時の mock_valkey パッチが効くようにする。
    from app.database import async_session
    from app.services.queue_service import purge_delivered
    from app.valkey_client import valkey

    await valkey.set(HEARTBEAT_KEY, "alive", ex=CHECK_INTERVAL * 3)

    async with async_session() as db:
        count = await purge_delivered(db, older_than_hours=PURGE_OLDER_THAN_HOURS)
    if count:
        logger.info("Purged %d delivered delivery jobs", count)
    return count


async def run_delivery_purge_loop() -> None:
    """delivered ジョブを 1 時間ごとにパージする。"""
    logger.info(
        "Delivery purge worker started (interval=%ds, older_than=%dh)",
        CHECK_INTERVAL,
        PURGE_OLDER_THAN_HOURS,
    )

    while True:
        try:
            await _run_once()
        except Exception:
            logger.exception("Error in delivery purge loop")

        await asyncio.sleep(CHECK_INTERVAL)
