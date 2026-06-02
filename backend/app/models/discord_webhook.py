import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class DiscordWebhook(Base):
    __tablename__ = "discord_webhooks"
    __table_args__ = (
        UniqueConstraint("user_id", "webhook_url", name="uq_discord_webhooks_user_url"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    webhook_url: Mapped[str] = mapped_column(Text, nullable=False)

    notify_mention: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_direct: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_quote: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_reaction: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_renote: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_follow: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_follow_request: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user = relationship("User", foreign_keys=[user_id])
