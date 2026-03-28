"""Add announcements and announcement_dismissals tables.

Revision ID: 037
Revises: 036
"""

import sqlalchemy as sa
from alembic import op

revision = "037"
down_revision = "036"


def upgrade() -> None:
    op.create_table(
        "announcements",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_html", sa.Text(), nullable=False),
        sa.Column("published", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("all_day", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "announcement_dismissals",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "announcement_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("announcements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_announcement_dismissals_announcement_id",
        "announcement_dismissals",
        ["announcement_id"],
    )
    op.create_index(
        "ix_announcement_dismissals_user_id",
        "announcement_dismissals",
        ["user_id"],
    )
    op.create_unique_constraint(
        "uq_announcement_dismissal",
        "announcement_dismissals",
        ["announcement_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_table("announcement_dismissals")
    op.drop_table("announcements")
