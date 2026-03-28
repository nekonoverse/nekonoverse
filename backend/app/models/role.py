"""動的ロール管理用の Role モデル。"""

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Role(Base):
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    permissions: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    quota_bytes: Mapped[int] = mapped_column(
        BigInteger, default=1073741824, server_default="1073741824"
    )  # 1 GB
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
