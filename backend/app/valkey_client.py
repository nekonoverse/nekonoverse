from valkey.asyncio import Valkey

from app.config import settings

valkey = Valkey.from_url(settings.valkey_url, decode_responses=True)
