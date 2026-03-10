"""Server settings service with Valkey caching."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.server_setting import ServerSetting

CACHE_TTL = 300  # 5 minutes


async def get_setting(db: AsyncSession, key: str) -> str | None:
    from app.valkey_client import valkey

    cached = await valkey.get(f"setting:{key}")
    if cached is not None:
        return cached if cached != "__NULL__" else None

    result = await db.execute(select(ServerSetting).where(ServerSetting.key == key))
    setting = result.scalar_one_or_none()
    value = setting.value if setting else None
    await valkey.set(f"setting:{key}", value or "__NULL__", ex=CACHE_TTL)
    return value


async def set_setting(db: AsyncSession, key: str, value: str | None) -> None:
    from app.valkey_client import valkey

    result = await db.execute(select(ServerSetting).where(ServerSetting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = value
    else:
        db.add(ServerSetting(key=key, value=value))
    await db.flush()
    await valkey.delete(f"setting:{key}")


async def get_all_settings(db: AsyncSession) -> dict[str, str | None]:
    result = await db.execute(select(ServerSetting))
    return {s.key: s.value for s in result.scalars().all()}
