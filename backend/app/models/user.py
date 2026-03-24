import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actors.id"), unique=True, nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(50),
        default="user",
        server_default="user",
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_system: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    private_key_pem: Mapped[str] = mapped_column(Text, nullable=False)
    totp_secret: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    totp_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    totp_recovery_codes: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, default=None)
    email_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    email_verification_token: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, default=None
    )
    email_verification_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    password_reset_token: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, default=None
    )
    password_reset_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    preferences: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    approval_status: Mapped[str] = mapped_column(
        String(20),
        default="approved",
        server_default="approved",
        nullable=False,
    )
    registration_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    actor = relationship("Actor", back_populates="local_user", lazy="selectin")
    oauth_tokens = relationship("OAuthToken", back_populates="user")
    passkey_credentials = relationship(
        "PasskeyCredential",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    drive_files = relationship("DriveFile", back_populates="owner")
    lists = relationship("List", back_populates="user", cascade="all, delete-orphan")

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_moderator(self) -> bool:
        return self.role == "moderator"

    @property
    def is_staff(self) -> bool:
        return self.role != "user"
