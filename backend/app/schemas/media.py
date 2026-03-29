import uuid
from datetime import datetime

from pydantic import BaseModel


class MediaAttachment(BaseModel):
    """Mastodon 互換の MediaAttachment レスポンス。"""

    id: str
    type: str
    url: str
    preview_url: str
    description: str | None
    blurhash: str | None
    meta: dict | None = None

    model_config = {"from_attributes": True}


class DriveFileResponse(BaseModel):
    id: uuid.UUID
    filename: str
    mime_type: str
    size_bytes: int
    url: str
    width: int | None
    height: int | None
    description: str | None
    blurhash: str | None
    focal_x: float | None = None
    focal_y: float | None = None
    server_file: bool
    created_at: datetime

    model_config = {"from_attributes": True}
