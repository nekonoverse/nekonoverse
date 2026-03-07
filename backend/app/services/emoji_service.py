import uuid

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


async def get_emoji_by_id(db: AsyncSession, emoji_id: uuid.UUID) -> CustomEmoji | None:
    result = await db.execute(
        select(CustomEmoji).where(CustomEmoji.id == emoji_id)
    )
    return result.scalar_one_or_none()


async def create_local_emoji(
    db: AsyncSession,
    shortcode: str,
    url: str,
    drive_file_id: uuid.UUID | None = None,
    **kwargs,
) -> CustomEmoji:
    emoji = CustomEmoji(
        shortcode=shortcode,
        domain=None,
        url=url,
        drive_file_id=drive_file_id,
        visible_in_picker=True,
        **kwargs,
    )
    db.add(emoji)
    await db.flush()
    return emoji


async def update_emoji(
    db: AsyncSession, emoji_id: uuid.UUID, updates: dict
) -> CustomEmoji | None:
    emoji = await get_emoji_by_id(db, emoji_id)
    if not emoji:
        return None
    for key, value in updates.items():
        if hasattr(emoji, key):
            setattr(emoji, key, value)
    await db.flush()
    return emoji


async def delete_emoji(db: AsyncSession, emoji_id: uuid.UUID) -> bool:
    emoji = await get_emoji_by_id(db, emoji_id)
    if not emoji:
        return False
    await db.delete(emoji)
    await db.flush()
    return True


async def upsert_remote_emoji(
    db: AsyncSession,
    shortcode: str,
    domain: str,
    url: str,
    static_url: str | None = None,
    aliases: list[str] | None = None,
    license: str | None = None,
    is_sensitive: bool = False,
    author: str | None = None,
    description: str | None = None,
    copy_permission: str | None = None,
    usage_info: str | None = None,
    is_based_on: str | None = None,
    category: str | None = None,
) -> CustomEmoji:
    existing = await get_custom_emoji(db, shortcode, domain)
    if existing:
        existing.url = url
        if static_url:
            existing.static_url = static_url
        if aliases is not None:
            existing.aliases = aliases
        if license:
            existing.license = license
        existing.is_sensitive = is_sensitive
        if author:
            existing.author = author
        if description:
            existing.description = description
        if copy_permission:
            existing.copy_permission = copy_permission
        if usage_info:
            existing.usage_info = usage_info
        if is_based_on:
            existing.is_based_on = is_based_on
        if category:
            existing.category = category
        await db.flush()
        return existing

    emoji = CustomEmoji(
        shortcode=shortcode,
        domain=domain,
        url=url,
        static_url=static_url,
        visible_in_picker=False,
        aliases=aliases,
        license=license,
        is_sensitive=is_sensitive,
        author=author,
        description=description,
        copy_permission=copy_permission,
        usage_info=usage_info,
        is_based_on=is_based_on,
        category=category,
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


async def list_all_local_emojis(db: AsyncSession) -> list[CustomEmoji]:
    result = await db.execute(
        select(CustomEmoji).where(
            CustomEmoji.domain.is_(None),
        ).order_by(CustomEmoji.category, CustomEmoji.shortcode)
    )
    return list(result.scalars().all())
