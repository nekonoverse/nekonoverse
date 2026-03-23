import logging
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_emoji import CustomEmoji

logger = logging.getLogger(__name__)

_SHORTCODE_PATTERN = re.compile(r"^[a-zA-Z0-9_]+$")
_SHORTCODE_MAX_LEN = 255


def validate_shortcode(shortcode: str) -> str:
    """Validate and return the shortcode, raising ValueError if invalid."""
    if not shortcode or len(shortcode) > _SHORTCODE_MAX_LEN:
        raise ValueError(
            f"Shortcode must be 1-{_SHORTCODE_MAX_LEN} characters: {shortcode!r}"
        )
    if not _SHORTCODE_PATTERN.match(shortcode):
        raise ValueError(
            f"Shortcode must contain only alphanumerics and underscores: {shortcode!r}"
        )
    return shortcode


def sanitize_shortcode(shortcode: str) -> str:
    """Replace invalid characters with underscores."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", shortcode).strip("_")


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
    result = await db.execute(select(CustomEmoji).where(CustomEmoji.id == emoji_id))
    return result.scalar_one_or_none()


async def create_local_emoji(
    db: AsyncSession,
    shortcode: str,
    url: str,
    drive_file_id: uuid.UUID | None = None,
    **kwargs,
) -> CustomEmoji:
    validate_shortcode(shortcode)
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
    await _invalidate_emoji_cache()
    return emoji


_EMOJI_UPDATABLE_FIELDS = {
    "shortcode",
    "category",
    "visible_in_picker",
    "aliases",
    "license",
    "is_sensitive",
    "local_only",
    "author",
    "description",
    "copy_permission",
}


async def _invalidate_emoji_cache() -> None:
    """Invalidate the Valkey emoji list cache."""
    try:
        from app.valkey_client import valkey as valkey_client

        await valkey_client.delete("perf:custom_emojis")
    except Exception:
        pass


async def update_emoji(db: AsyncSession, emoji_id: uuid.UUID, updates: dict) -> CustomEmoji | None:
    emoji = await get_emoji_by_id(db, emoji_id)
    if not emoji:
        return None
    if "shortcode" in updates and updates["shortcode"] is not None:
        validate_shortcode(updates["shortcode"])
    for key, value in updates.items():
        if key in _EMOJI_UPDATABLE_FIELDS:
            setattr(emoji, key, value)
    await db.flush()
    await _invalidate_emoji_cache()
    return emoji


async def delete_emoji(db: AsyncSession, emoji_id: uuid.UUID) -> bool:
    emoji = await get_emoji_by_id(db, emoji_id)
    if not emoji:
        return False
    await db.delete(emoji)
    await db.flush()
    await _invalidate_emoji_cache()
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


async def fetch_and_cache_remote_emoji(
    db: AsyncSession, shortcode: str, domain: str
) -> CustomEmoji | None:
    """Fetch a remote custom emoji from the instance API and cache it.

    Tries GET https://{domain}/api/v1/custom_emojis to find the emoji.
    Returns the cached CustomEmoji or None if not found / fetch failed.
    """
    existing = await get_custom_emoji(db, shortcode, domain)
    if existing:
        return existing

    try:
        from app.utils.http_client import make_async_client
        from app.utils.network import is_safe_url

        url = f"https://{domain}/api/v1/custom_emojis"
        if not is_safe_url(url):
            return None

        async with make_async_client(timeout=5.0, follow_redirects=False) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        emojis = resp.json()
        if not isinstance(emojis, list):
            return None

        for entry in emojis:
            if not isinstance(entry, dict):
                continue
            if entry.get("shortcode") == shortcode:
                emoji_url = entry.get("url")
                if not emoji_url:
                    return None
                return await upsert_remote_emoji(
                    db,
                    shortcode,
                    domain,
                    emoji_url,
                    static_url=entry.get("static_url"),
                    category=entry.get("category"),
                )
    except Exception:
        logger.debug("Failed to fetch remote emoji :%s: from %s", shortcode, domain)
    return None


async def list_remote_emoji_sources(
    db: AsyncSession, shortcode: str
) -> list[CustomEmoji]:
    """Return all remote entries matching the given shortcode."""
    result = await db.execute(
        select(CustomEmoji)
        .where(
            CustomEmoji.shortcode == shortcode,
            CustomEmoji.domain.isnot(None),
        )
        .order_by(CustomEmoji.domain)
    )
    return list(result.scalars().all())


async def list_local_emojis(db: AsyncSession) -> list[CustomEmoji]:
    result = await db.execute(
        select(CustomEmoji)
        .where(
            CustomEmoji.domain.is_(None),
            CustomEmoji.visible_in_picker.is_(True),
        )
        .order_by(CustomEmoji.shortcode)
    )
    return list(result.scalars().all())


async def list_all_local_emojis(db: AsyncSession) -> list[CustomEmoji]:
    result = await db.execute(
        select(CustomEmoji)
        .where(
            CustomEmoji.domain.is_(None),
        )
        .order_by(CustomEmoji.category, CustomEmoji.shortcode)
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
        escaped = search.replace("%", r"\%").replace("_", r"\_")
        query = query.where(CustomEmoji.shortcode.ilike(f"%{escaped}%"))
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


async def import_remote_emoji_to_local(db: AsyncSession, emoji_id: uuid.UUID) -> CustomEmoji:
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
    from app.utils.network import is_safe_url

    if not is_safe_url(remote.url):
        raise ValueError("Remote emoji URL points to a private or invalid host")

    from app.utils.http_client import make_async_client

    async with make_async_client(timeout=30.0, follow_redirects=False) as client:
        resp = await client.get(remote.url)
        # Follow one redirect manually with SSRF re-validation
        if resp.is_redirect:
            redirect_url = str(resp.next_request.url) if resp.next_request else None
            if not redirect_url or not is_safe_url(redirect_url):
                raise ValueError("Redirect to unsafe URL")
            resp = await client.get(redirect_url)
        resp.raise_for_status()

    mime_type = resp.headers.get("content-type", "image/png").split(";")[0].strip()
    data = resp.content

    from app.services.drive_service import ALLOWED_IMAGE_TYPES

    if mime_type not in ALLOWED_IMAGE_TYPES:
        raise ValueError(f"Unsupported image type: {mime_type}")

    from app.services.drive_service import file_to_url, upload_drive_file

    drive_file = await upload_drive_file(
        db=db,
        owner=None,
        data=data,
        filename=f"emoji_{remote.shortcode}",
        mime_type=mime_type,
        server_file=True,
    )
    url = file_to_url(drive_file)

    local = await create_local_emoji(
        db,
        shortcode=remote.shortcode,
        url=url,
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
