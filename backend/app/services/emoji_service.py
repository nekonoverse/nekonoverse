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


async def get_emojis_by_shortcodes(
    db: AsyncSession,
    shortcodes: set[str],
    domain: str | None = None,
) -> list[CustomEmoji]:
    """Fetch multiple emoji by shortcode for a given domain (or local if None)."""
    if not shortcodes:
        return []
    result = await db.execute(
        select(CustomEmoji).where(
            CustomEmoji.shortcode.in_(shortcodes),
            CustomEmoji.domain == domain,
        )
    )
    return list(result.scalars().all())


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


async def list_remote_emojis(
    db: AsyncSession,
    domain: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[CustomEmoji]:
    """List remote (cached) emoji, optionally filtered by domain/shortcode."""
    query = select(CustomEmoji).where(CustomEmoji.domain.isnot(None))
    if domain:
        query = query.where(CustomEmoji.domain == domain)
    if search:
        query = query.where(CustomEmoji.shortcode.ilike(f"%{search}%"))
    query = query.order_by(CustomEmoji.domain, CustomEmoji.shortcode).limit(limit).offset(offset)
    result = await db.execute(query)
    return list(result.scalars().all())


async def list_remote_emoji_domains(db: AsyncSession) -> list[str]:
    """Get distinct domains from cached remote emoji."""
    result = await db.execute(
        select(CustomEmoji.domain)
        .where(CustomEmoji.domain.isnot(None))
        .distinct()
        .order_by(CustomEmoji.domain)
    )
    return [row[0] for row in result.all()]


async def import_remote_emoji_to_local(
    db: AsyncSession, emoji_id: uuid.UUID
) -> CustomEmoji:
    """Download a remote emoji image and create a local copy."""
    remote = await get_emoji_by_id(db, emoji_id)
    if not remote or remote.domain is None:
        raise ValueError("Remote emoji not found")

    if remote.copy_permission == "deny":
        raise ValueError("Import denied by author (copy_permission=deny)")

    existing = await get_custom_emoji(db, remote.shortcode, None)
    if existing:
        raise ValueError(f"Local emoji :{remote.shortcode}: already exists")

    # Download image from remote URL
    import httpx
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(remote.url)
        resp.raise_for_status()

    mime_type = resp.headers.get("content-type", "image/png").split(";")[0].strip()
    data = resp.content

    from app.services.drive_service import ALLOWED_IMAGE_TYPES
    if mime_type not in ALLOWED_IMAGE_TYPES:
        raise ValueError(f"Unsupported image type: {mime_type}")

    from app.services.drive_service import file_to_url, upload_drive_file
    drive_file = await upload_drive_file(
        db=db, owner=None, data=data,
        filename=f"emoji_{remote.shortcode}",
        mime_type=mime_type, server_file=True,
    )
    url = file_to_url(drive_file)

    local = await create_local_emoji(
        db, shortcode=remote.shortcode, url=url,
        drive_file_id=drive_file.id,
        category=remote.category,
        aliases=remote.aliases,
        license=remote.license,
        is_sensitive=remote.is_sensitive,
        author=remote.author,
        description=remote.description,
        copy_permission=remote.copy_permission,
        usage_info=remote.usage_info,
        is_based_on=remote.is_based_on,
        import_from=remote.domain,
    )
    return local
