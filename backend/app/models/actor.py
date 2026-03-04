import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Actor(Base):
    __tablename__ = "actors"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ap_id: Mapped[str] = mapped_column(String(2048), unique=True, nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(50), default="Person", nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    header_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    inbox_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    outbox_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    shared_inbox_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    followers_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    following_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    public_key_pem: Mapped[str] = mapped_column(Text, nullable=False)
    is_cat: Mapped[bool] = mapped_column(Boolean, default=False)
    manually_approves_followers: Mapped[bool] = mapped_column(Boolean, default=False)
    discoverable: Mapped[bool] = mapped_column(Boolean, default=True)
    fields: Mapped[list | None] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    local_user = relationship("User", back_populates="actor", uselist=False, lazy="selectin")
    notes = relationship("Note", back_populates="actor")
    reactions = relationship("Reaction", back_populates="actor")

    __table_args__ = (
        UniqueConstraint("username", "domain", name="uq_actors_username_domain"),
        Index("ix_actors_domain_username", "domain", "username"),
        Index("ix_actors_lower_username_domain", func.lower(username), "domain", unique=True),
    )

    @property
    def is_local(self) -> bool:
        return self.domain is None
