import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Reaction(Base):
    __tablename__ = "reactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ap_id: Mapped[str | None] = mapped_column(String(2048), unique=True, nullable=True, index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actors.id"), nullable=False, index=True
    )
    note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notes.id"), nullable=False, index=True
    )
    emoji: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    actor = relationship("Actor", back_populates="reactions")
    note = relationship("Note", back_populates="reactions")

    __table_args__ = (
        UniqueConstraint("actor_id", "note_id", "emoji", name="uq_reactions_actor_note_emoji"),
        Index("ix_reactions_note_emoji", "note_id", "emoji"),
    )
