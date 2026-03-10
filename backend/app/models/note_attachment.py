import uuid

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class NoteAttachment(Base):
    __tablename__ = "note_attachments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    drive_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drive_files.id", ondelete="SET NULL"), nullable=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # For remote attachments where we don't download the file
    remote_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    remote_mime_type: Mapped[str | None] = mapped_column(String(127), nullable=True)
    remote_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    remote_blurhash: Mapped[str | None] = mapped_column(String(100), nullable=True)
    remote_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remote_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remote_description: Mapped[str | None] = mapped_column(String(1500), nullable=True)
    remote_focal_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    remote_focal_y: Mapped[float | None] = mapped_column(Float, nullable=True)

    note = relationship("Note", back_populates="attachments")
    drive_file = relationship("DriveFile", lazy="selectin")
