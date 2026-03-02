from valkey.asyncio import ConnectionPool, Valkey

from app.config import settings

valkey_pool = ConnectionPool.from_url(settings.valkey_url, decode_responses=True)


def get_valkey() -> Valkey:
    return Valkey(connection_pool=valkey_pool)
