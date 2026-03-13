import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actors.id"), nullable=False, index=True
    )
    session_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    key_p256dh: Mapped[str] = mapped_column(String(255), nullable=False)
    key_auth: Mapped[str] = mapped_column(String(255), nullable=False)
    alerts: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: {
            "mention": True,
            "follow": True,
            "favourite": True,
            "reblog": True,
            "poll": True,
        },
    )
    policy: Mapped[str] = mapped_column(String(20), nullable=False, default="all")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    actor = relationship("Actor", foreign_keys=[actor_id])
