import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ServerSettingsResponse(BaseModel):
    server_name: str | None = None
    server_description: str | None = None
    tos_url: str | None = None
    registration_open: bool = True
    server_icon_url: str | None = None


class ServerSettingsUpdate(BaseModel):
    server_name: str | None = Field(None, max_length=255)
    server_description: str | None = Field(None, max_length=2000)
    tos_url: str | None = Field(None, max_length=2048)
    registration_open: bool | None = None


class AdminUserResponse(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    display_name: str | None
    role: str
    is_active: bool
    suspended: bool = False
    silenced: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class RoleChangeRequest(BaseModel):
    role: str = Field(pattern=r"^(user|moderator|admin)$")


class ModerationActionRequest(BaseModel):
    reason: str | None = Field(None, max_length=2000)


class DomainBlockRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=255)
    severity: str = Field(default="suspend", pattern=r"^(suspend|silence)$")
    reason: str | None = Field(None, max_length=2000)


class DomainBlockResponse(BaseModel):
    id: uuid.UUID
    domain: str
    severity: str
    reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ReportResponse(BaseModel):
    id: uuid.UUID
    reporter: str
    target: str
    target_note_id: uuid.UUID | None
    comment: str | None
    status: str
    created_at: datetime
    resolved_at: datetime | None

    model_config = {"from_attributes": True}


class AdminStatsResponse(BaseModel):
    user_count: int
    note_count: int
    domain_count: int


class ModerationLogResponse(BaseModel):
    id: uuid.UUID
    moderator: str
    action: str
    target_type: str
    target_id: str
    reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminEmojiResponse(BaseModel):
    id: uuid.UUID
    shortcode: str
    url: str
    static_url: str | None = None
    visible_in_picker: bool = True
    category: str | None = None
    aliases: list[str] | None = None
    license: str | None = None
    is_sensitive: bool = False
    local_only: bool = False
    author: str | None = None
    description: str | None = None
    copy_permission: str | None = None
    usage_info: str | None = None
    is_based_on: str | None = None
    import_from: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminRemoteEmojiResponse(BaseModel):
    id: uuid.UUID
    shortcode: str
    domain: str | None = None
    url: str
    static_url: str | None = None
    category: str | None = None
    aliases: list[str] | None = None
    license: str | None = None
    is_sensitive: bool = False
    author: str | None = None
    description: str | None = None
    copy_permission: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ImportByShortcodeRequest(BaseModel):
    shortcode: str = Field(min_length=1, max_length=100)
    domain: str = Field(min_length=1, max_length=255)


class AdminEmojiUpdate(BaseModel):
    shortcode: str | None = Field(None, max_length=100, pattern=r"^[a-zA-Z0-9_]+$")
    category: str | None = Field(None, max_length=100)
    visible_in_picker: bool | None = None
    aliases: list[str] | None = None
    license: str | None = Field(None, max_length=1024)
    is_sensitive: bool | None = None
    local_only: bool | None = None
    author: str | None = Field(None, max_length=128)
    description: str | None = Field(None, max_length=512)
    copy_permission: str | None = Field(None, pattern=r"^(allow|deny|conditional)$")
    usage_info: str | None = Field(None, max_length=512)
    is_based_on: str | None = Field(None, max_length=1024)
