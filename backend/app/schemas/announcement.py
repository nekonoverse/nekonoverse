"""お知らせ用の Pydantic スキーマ。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AnnouncementCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=10000)
    published: bool = False
    all_day: bool = False
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class AnnouncementUpdateRequest(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    content: str | None = Field(None, min_length=1, max_length=10000)
    published: bool | None = None
    all_day: bool | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class AnnouncementAdminResponse(BaseModel):
    id: uuid.UUID
    title: str
    content: str
    content_html: str
    published: bool
    all_day: bool
    starts_at: datetime | None
    ends_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
