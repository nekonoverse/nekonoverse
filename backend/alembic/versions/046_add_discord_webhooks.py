"""Add discord_webhooks table for Discord-compatible webhook notifications.

ユーザーごとに任意数の Discord 互換 Webhook URL を登録でき、通知タイプごとに
boolean カラムで配送 ON/OFF を制御する。配送経路として既存の Web Push, SSE に
加えて第 3 の経路となる。

Revision ID: 046
Revises: 045
"""

import sqlalchemy as sa

from alembic import op

revision = "046"
down_revision = "045"


def upgrade() -> None:
    op.create_table(
        "discord_webhooks",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("webhook_url", sa.Text(), nullable=False),
        sa.Column("notify_mention", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("notify_direct", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("notify_quote", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("notify_reaction", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("notify_renote", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("notify_follow", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "notify_follow_request", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "consecutive_failures", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_discord_webhooks_user_id",
        "discord_webhooks",
        ["user_id"],
    )
    op.create_unique_constraint(
        "uq_discord_webhooks_user_url",
        "discord_webhooks",
        ["user_id", "webhook_url"],
    )


def downgrade() -> None:
    op.drop_table("discord_webhooks")
