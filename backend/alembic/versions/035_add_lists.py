"""Add lists and list_members tables.

Revision ID: 035
Revises: 034
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "035"
down_revision = "034"


def upgrade() -> None:
    op.create_table(
        "lists",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("replies_policy", sa.String(20), nullable=False, server_default="list"),
        sa.Column("exclusive", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_lists_user_id", "lists", ["user_id"])

    op.create_table(
        "list_members",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "list_id",
            UUID(as_uuid=True),
            sa.ForeignKey("lists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor_id", UUID(as_uuid=True), sa.ForeignKey("actors.id"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("list_id", "actor_id", name="uq_list_members_pair"),
    )
    op.create_index("ix_list_members_list_id", "list_members", ["list_id"])
    op.create_index("ix_list_members_actor_id", "list_members", ["actor_id"])


def downgrade() -> None:
    op.drop_table("list_members")
    op.drop_table("lists")
