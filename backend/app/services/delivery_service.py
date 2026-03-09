"""Activity delivery service -- enqueues activities for the worker to deliver."""

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
    """Enqueue an activity for delivery to a remote inbox."""
    # Check domain block
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

    # Notify worker via Valkey
    from app.valkey_client import valkey

    await valkey.lpush("delivery:queue", str(job.id))

    return job
