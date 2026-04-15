"""Valkeyキャッシュ付きサーバー設定サービス。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.server_setting import ServerSetting

CACHE_TTL = 300  # 5分


async def get_setting(db: AsyncSession, key: str) -> str | None:
    from app.valkey_client import valkey

    cached = await valkey.get(f"setting:{key}")
    if cached is not None:
        return cached if cached != "__NULL__" else None

    result = await db.execute(select(ServerSetting).where(ServerSetting.key == key))
    setting = result.scalar_one_or_none()
    value = setting.value if setting else None
    await valkey.set(f"setting:{key}", value if value is not None else "__NULL__", ex=CACHE_TTL)
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


async def get_settings_batch(db: AsyncSession, keys: list[str]) -> dict[str, str | None]:
    """複数の設定を一括取得する。Valkeyキャッシュを優先し、ミス分のみDBから1クエリで取得。"""
    from app.valkey_client import valkey

    if not keys:
        return {}

    result: dict[str, str | None] = {}
    cache_keys = [f"setting:{k}" for k in keys]
    cached_values = await valkey.mget(cache_keys)

    missing_keys: list[str] = []
    for key, cached in zip(keys, cached_values):
        if cached is not None:
            result[key] = cached if cached != "__NULL__" else None
        else:
            missing_keys.append(key)

    if missing_keys:
        db_result = await db.execute(
            select(ServerSetting).where(ServerSetting.key.in_(missing_keys))
        )
        db_settings = {s.key: s.value for s in db_result.scalars().all()}
        pipe = valkey.pipeline()
        for key in missing_keys:
            value = db_settings.get(key)
            result[key] = value
            pipe.set(f"setting:{key}", value if value is not None else "__NULL__", ex=CACHE_TTL)
        await pipe.execute()

    return result


async def get_all_settings(db: AsyncSession) -> dict[str, str | None]:
    result = await db.execute(select(ServerSetting))
    return {s.key: s.value for s in result.scalars().all()}
