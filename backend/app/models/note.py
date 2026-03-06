import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ap_id: Mapped[str] = mapped_column(String(2048), unique=True, nullable=False, index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actors.id"), nullable=False, index=True
    )
    in_reply_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notes.id"), nullable=True, index=True
    )
    in_reply_to_ap_id: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    renote_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notes.id"), nullable=True, index=True
    )
    renote_of_ap_id: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), default="public", nullable=False)
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    spoiler_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    to: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    cc: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    published: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replies_count: Mapped[int] = mapped_column(Integer, default=0)
    reactions_count: Mapped[int] = mapped_column(Integer, default=0)
    renotes_count: Mapped[int] = mapped_column(Integer, default=0)
    local: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    actor = relationship("Actor", back_populates="notes")
    reactions = relationship("Reaction", back_populates="note")

    __table_args__ = (
        Index("ix_notes_actor_published", "actor_id", "published"),
        Index("ix_notes_local_published", "local", "published"),
    )
