"""Notifications, bookmarks, user blocks, user mutes

Revision ID: 009
Revises: 008
Create Date: 2026-03-06 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("actors.id"), nullable=False, index=True),
        sa.Column("sender_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("actors.id"), nullable=True),
        sa.Column("note_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("notes.id"), nullable=True),
        sa.Column("reaction_emoji", sa.String(200), nullable=True),
        sa.Column("read", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )

    op.create_table(
        "bookmarks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("actors.id"), nullable=False, index=True),
        sa.Column("note_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("notes.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("actor_id", "note_id", name="uq_bookmarks_actor_note"),
    )

    op.create_table(
        "user_blocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("actors.id"), nullable=False, index=True),
        sa.Column("target_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("actors.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("actor_id", "target_id", name="uq_user_blocks_actor_target"),
    )

    op.create_table(
        "user_mutes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("actors.id"), nullable=False, index=True),
        sa.Column("target_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("actors.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("actor_id", "target_id", name="uq_user_mutes_actor_target"),
    )


def downgrade() -> None:
    op.drop_table("user_mutes")
    op.drop_table("user_blocks")
    op.drop_table("bookmarks")
    op.drop_table("notifications")
