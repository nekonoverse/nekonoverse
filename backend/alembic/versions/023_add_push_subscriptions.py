"""Add push_subscriptions table for Web Push notifications.

Revision ID: 023
Revises: 022
"""

import sqlalchemy as sa
from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("actor_id", sa.UUID(), sa.ForeignKey("actors.id"), nullable=False),
        sa.Column("session_id", sa.String(255), nullable=False, unique=True),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("key_p256dh", sa.String(255), nullable=False),
        sa.Column("key_auth", sa.String(255), nullable=False),
        sa.Column("alerts", sa.JSON(), nullable=False),
        sa.Column("policy", sa.String(20), nullable=False, server_default="all"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_push_subscriptions_actor_id", "push_subscriptions", ["actor_id"])


def downgrade() -> None:
    op.drop_table("push_subscriptions")
