import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CustomEmoji(Base):
    __tablename__ = "custom_emojis"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shortcode: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    static_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    visible_in_picker: Mapped[bool] = mapped_column(Boolean, default=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Misskey-compatible fields
    aliases: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    license: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    local_only: Mapped[bool] = mapped_column(Boolean, default=False)

    # CherryPick (yojo-art) fields
    author: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    copy_permission: Mapped[str | None] = mapped_column(String(20), nullable=True)
    usage_info: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_based_on: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    import_from: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Link to DriveFile for local emoji images
    drive_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drive_files.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("shortcode", "domain", name="uq_custom_emojis_shortcode_domain"),
        Index("ix_custom_emojis_shortcode_domain", "shortcode", "domain"),
    )
