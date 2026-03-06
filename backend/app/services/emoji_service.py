from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_emoji import CustomEmoji


async def get_custom_emoji(
    db: AsyncSession, shortcode: str, domain: str | None = None
) -> CustomEmoji | None:
    result = await db.execute(
        select(CustomEmoji).where(
            CustomEmoji.shortcode == shortcode,
            CustomEmoji.domain == domain,
        )
    )
    return result.scalar_one_or_none()


async def upsert_remote_emoji(
    db: AsyncSession, shortcode: str, domain: str, url: str, static_url: str | None = None
) -> CustomEmoji:
    existing = await get_custom_emoji(db, shortcode, domain)
    if existing:
        existing.url = url
        if static_url:
            existing.static_url = static_url
        await db.flush()
        return existing

    emoji = CustomEmoji(
        shortcode=shortcode,
        domain=domain,
        url=url,
        static_url=static_url,
        visible_in_picker=False,
    )
    db.add(emoji)
    await db.flush()
    return emoji


async def list_local_emojis(db: AsyncSession) -> list[CustomEmoji]:
    result = await db.execute(
        select(CustomEmoji).where(
            CustomEmoji.domain.is_(None),
            CustomEmoji.visible_in_picker.is_(True),
        ).order_by(CustomEmoji.shortcode)
    )
    return list(result.scalars().all())
