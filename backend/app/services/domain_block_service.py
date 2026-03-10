"""Domain block service with Valkey caching."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain_block import DomainBlock
from app.models.user import User

logger = logging.getLogger(__name__)

CACHE_TTL = 300


async def create_domain_block(
    db: AsyncSession, domain: str, severity: str, reason: str | None, user: User
) -> DomainBlock:
    domain = domain.lower().strip()
    block = DomainBlock(
        domain=domain,
        severity=severity,
        reason=reason,
        created_by_id=user.id,
    )
    db.add(block)
    await db.flush()

    from app.valkey_client import valkey

    await valkey.delete(f"domain_block:{domain}")

    logger.info("Domain blocked: %s (severity=%s) by %s", domain, severity, user.actor.username)
    return block


async def remove_domain_block(db: AsyncSession, domain: str) -> bool:
    domain = domain.lower().strip()
    result = await db.execute(select(DomainBlock).where(DomainBlock.domain == domain))
    block = result.scalar_one_or_none()
    if not block:
        return False
    await db.delete(block)
    await db.flush()

    from app.valkey_client import valkey

    await valkey.delete(f"domain_block:{domain}")
    return True


async def list_domain_blocks(db: AsyncSession) -> list[DomainBlock]:
    result = await db.execute(select(DomainBlock).order_by(DomainBlock.created_at.desc()))
    return list(result.scalars().all())


async def is_domain_blocked(db: AsyncSession, domain: str) -> bool:
    if not domain:
        return False
    domain = domain.lower().strip()

    from app.valkey_client import valkey

    cached = await valkey.get(f"domain_block:{domain}")
    if cached is not None:
        return cached == "1"

    result = await db.execute(select(DomainBlock.id).where(DomainBlock.domain == domain))
    blocked = result.scalar_one_or_none() is not None
    await valkey.set(f"domain_block:{domain}", "1" if blocked else "0", ex=CACHE_TTL)
    return blocked
