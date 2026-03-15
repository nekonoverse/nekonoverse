import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ServerSettingsResponse(BaseModel):
    server_name: str | None = None
    server_description: str | None = None
    tos_url: str | None = None
    registration_open: bool = True
    registration_mode: str = "open"
    invite_create_role: str = "admin"
    server_icon_url: str | None = None
    server_theme_color: str | None = None
    push_enabled: bool = True
    vapid_public_key: str | None = None


class ServerSettingsUpdate(BaseModel):
    server_name: str | None = Field(None, max_length=255)
    server_description: str | None = Field(None, max_length=2000)
    tos_url: str | None = Field(None, max_length=2048)
    registration_open: bool | None = None
    registration_mode: str | None = Field(None, pattern=r"^(open|invite|closed|approval)$")
    invite_create_role: str | None = Field(None, pattern=r"^(admin|moderator|user)$")
    server_theme_color: str | None = Field(
        None, max_length=7, pattern=r"^#[0-9a-fA-F]{6}$"
    )
    push_enabled: bool | None = None


class AdminUserResponse(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    display_name: str | None
    role: str
    is_active: bool
    is_system: bool = False
    suspended: bool = False
    silenced: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class PendingRegistrationResponse(BaseModel):
    """Pending registration awaiting admin approval."""

    id: uuid.UUID
    username: str
    email: str
    reason: str | None = None
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


# --- Federation ---


class DeliveryStatsResponse(BaseModel):
    """Delivery statistics for a federated server."""

    success: int = 0
    failure: int = 0
    pending: int = 0
    dead: int = 0


class FederatedServerResponse(BaseModel):
    """Summary of a federated remote server."""

    domain: str
    user_count: int
    note_count: int
    last_activity_at: datetime | None
    first_seen_at: datetime | None
    status: str
    block_severity: str | None = None
    delivery_stats: DeliveryStatsResponse


class FederatedServerListResponse(BaseModel):
    """Paginated list of federated servers."""

    servers: list[FederatedServerResponse]
    total: int


class ActorSummaryResponse(BaseModel):
    """Brief actor info for federation detail view."""

    username: str
    display_name: str | None
    ap_id: str
    last_fetched_at: datetime | None


class FederatedServerDetailResponse(FederatedServerResponse):
    """Detailed info for a single federated server."""

    block_reason: str | None = None
    recent_actors: list[ActorSummaryResponse]


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


# --- Queue Management ---


class QueueStatsResponse(BaseModel):
    """Overall delivery queue statistics."""

    pending: int = 0
    processing: int = 0
    delivered: int = 0
    dead: int = 0
    total: int = 0
    recent_delivered: int = 0
    recent_dead: int = 0


class QueueJobResponse(BaseModel):
    """Single delivery queue job."""

    id: uuid.UUID
    target_inbox_url: str
    status: str
    attempts: int
    max_attempts: int
    error_message: str | None
    created_at: datetime
    last_attempted_at: datetime | None
    next_retry_at: datetime | None

    model_config = {"from_attributes": True}


class QueueJobListResponse(BaseModel):
    """Paginated list of queue jobs."""

    jobs: list[QueueJobResponse]
    total: int


# --- System Stats ---


class SystemStatsResponse(BaseModel):
    """System resource and service health stats."""

    # Database pool
    db_pool_size: int = 0
    db_pool_checked_in: int = 0
    db_pool_checked_out: int = 0
    db_pool_overflow: int = 0
    # Valkey
    valkey_connected_clients: int = 0
    valkey_used_memory_human: str = ""
    valkey_total_keys: int = 0
    # System
    load_avg_1m: float = 0.0
    load_avg_5m: float = 0.0
    load_avg_15m: float = 0.0
    memory_total_mb: int = 0
    memory_available_mb: int = 0
    memory_percent: float = 0.0
    uptime_seconds: float = 0.0
    # Worker
    worker_alive: bool = False
    worker_last_heartbeat: str | None = None
