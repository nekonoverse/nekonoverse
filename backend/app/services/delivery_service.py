"""Activity delivery service -- enqueues activities for the worker to deliver."""

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.delivery import DeliveryJob


async def enqueue_delivery(
    db: AsyncSession,
    actor_id: uuid.UUID,
    target_inbox_url: str,
    payload: dict,
) -> DeliveryJob:
    """Enqueue an activity for delivery to a remote inbox."""
    job = DeliveryJob(
        actor_id=actor_id,
        target_inbox_url=target_inbox_url,
        payload=payload,
        status="pending",
    )
    db.add(job)
    await db.commit()

    # Notify worker via Valkey
    from app.valkey_client import valkey_pool

    async with valkey_pool.client() as conn:
        await conn.lpush("delivery:queue", str(job.id))

    return job
