"""Add TOTP two-factor authentication fields to users

Revision ID: 017
Revises: 016
Create Date: 2026-03-10
"""

import sqlalchemy as sa

from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("totp_secret", sa.Text(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "totp_enabled",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("totp_recovery_codes", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "totp_recovery_codes")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
