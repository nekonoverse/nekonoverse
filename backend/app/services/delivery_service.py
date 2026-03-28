"""Activity 配送サービス -- ワーカーによる配送のためにアクティビティをキューに追加する。"""

import logging
import uuid
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.delivery import DeliveryJob

logger = logging.getLogger(__name__)


async def enqueue_delivery(
    db: AsyncSession,
    actor_id: uuid.UUID,
    target_inbox_url: str,
    payload: dict,
) -> DeliveryJob | None:
    """リモート inbox への配送用にアクティビティをキューに追加する。"""
    # ドメインブロックの確認
    domain = urlparse(target_inbox_url).hostname
    if domain:
        from app.services.domain_block_service import is_domain_blocked

        if await is_domain_blocked(db, domain):
            logger.info("Skipping delivery to blocked domain: %s", domain)
            return None

    job = DeliveryJob(
        actor_id=actor_id,
        target_inbox_url=target_inbox_url,
        payload=payload,
        status="pending",
    )
    db.add(job)
    await db.commit()

    # Valkey 経由でワーカーに通知
    from app.valkey_client import valkey

    await valkey.lpush("delivery:queue", str(job.id))

    return job


async def enqueue_deliveries(
    db: AsyncSession,
    actor_id: uuid.UUID,
    inbox_urls: list[str],
    payload: dict,
) -> list[DeliveryJob]:
    """H-3: 配送ジョブを一括でキューに追加する (単一コミット)。"""
    from app.services.domain_block_service import is_domain_blocked

    jobs = []
    for url in inbox_urls:
        domain = urlparse(url).hostname
        if domain and await is_domain_blocked(db, domain):
            logger.info("Skipping delivery to blocked domain: %s", domain)
            continue
        jobs.append(DeliveryJob(
            actor_id=actor_id,
            target_inbox_url=url,
            payload=payload,
            status="pending",
        ))

    if not jobs:
        return []

    db.add_all(jobs)
    await db.commit()

    # Valkey 経由でワーカーに通知
    from app.valkey_client import valkey

    pipe = valkey.pipeline()
    for job in jobs:
        pipe.lpush("delivery:queue", str(job.id))
    await pipe.execute()

    return jobs
