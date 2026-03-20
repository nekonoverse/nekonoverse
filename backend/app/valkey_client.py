from valkey.asyncio import Valkey
from valkey.asyncio.connection import ConnectionPool

from app.config import settings

_pool = ConnectionPool.from_url(
    settings.valkey_url,
    decode_responses=True,
    socket_timeout=10,
    socket_connect_timeout=5,
    max_connections=settings.valkey_max_connections,
    retry_on_timeout=True,
)

valkey = Valkey(connection_pool=_pool)
