"""Discord 互換 Webhook 通知設定の Pydantic スキーマ。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class DiscordWebhookCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    webhook_url: HttpUrl
    notify_mention: bool = True
    notify_direct: bool = True
    notify_quote: bool = True
    notify_reaction: bool = True
    notify_renote: bool = True
    notify_follow: bool = True
    notify_follow_request: bool = True
    enabled: bool = True


class DiscordWebhookUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    webhook_url: HttpUrl | None = None
    notify_mention: bool | None = None
    notify_direct: bool | None = None
    notify_quote: bool | None = None
    notify_reaction: bool | None = None
    notify_renote: bool | None = None
    notify_follow: bool | None = None
    notify_follow_request: bool | None = None
    enabled: bool | None = None


class DiscordWebhookResponse(BaseModel):
    id: uuid.UUID
    name: str
    # 生の URL ではなくマスク済み (末尾トークンを伏せる) を返す
    webhook_url_masked: str
    notify_mention: bool
    notify_direct: bool
    notify_quote: bool
    notify_reaction: bool
    notify_renote: bool
    notify_follow: bool
    notify_follow_request: bool
    enabled: bool
    consecutive_failures: int
    last_error: str | None
    last_delivered_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DiscordWebhookTestResponse(BaseModel):
    success: bool
    status_code: int | None = None
    error: str | None = None
