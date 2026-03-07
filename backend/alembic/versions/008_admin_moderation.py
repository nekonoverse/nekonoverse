"""Admin and moderation tables

Revision ID: 008
Revises: 007
Create Date: 2026-03-06 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Actor moderation columns
    op.add_column("actors", sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("actors", sa.Column("silenced_at", sa.DateTime(timezone=True), nullable=True))

    # Domain blocks
    op.create_table(
        "domain_blocks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("domain", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("severity", sa.String(20), nullable=False, server_default="suspend"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Reports
    op.create_table(
        "reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("ap_id", sa.String(2048), unique=True, nullable=True),
        sa.Column("reporter_actor_id", UUID(as_uuid=True), sa.ForeignKey("actors.id"), nullable=False),
        sa.Column("target_actor_id", UUID(as_uuid=True), sa.ForeignKey("actors.id"), nullable=False),
        sa.Column("target_note_id", UUID(as_uuid=True), sa.ForeignKey("notes.id"), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("resolved_by_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_reports_status", "reports", ["status"])
    op.create_index("ix_reports_target_actor", "reports", ["target_actor_id"])

    # Server settings
    op.create_table(
        "server_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Moderation log
    op.create_table(
        "moderation_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("moderator_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("target_id", sa.String(255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_moderation_log_created", "moderation_log", ["created_at"])

    # Seed default settings
    op.execute(
        "INSERT INTO server_settings (key, value, updated_at) VALUES "
        "('server_name', 'Nekonoverse', NOW()), "
        "('server_description', 'A cat-friendly ActivityPub server', NOW())"
    )


def downgrade() -> None:
    op.drop_table("moderation_log")
    op.drop_table("server_settings")
    op.drop_index("ix_reports_target_actor", table_name="reports")
    op.drop_index("ix_reports_status", table_name="reports")
    op.drop_table("reports")
    op.drop_table("domain_blocks")
    op.drop_column("actors", "silenced_at")
    op.drop_column("actors", "suspended_at")
