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
