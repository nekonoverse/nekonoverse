"""Add login_history table.

Revision ID: 030
Revises: 029
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "030"
down_revision = "029"


def upgrade() -> None:
    op.create_table(
        "login_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=False),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("success", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_login_history_user_id", "login_history", ["user_id"])
    op.create_index("ix_login_history_created_at", "login_history", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_login_history_created_at", table_name="login_history")
    op.drop_index("ix_login_history_user_id", table_name="login_history")
    op.drop_table("login_history")
