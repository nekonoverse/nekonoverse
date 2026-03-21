"""Add email verification and password reset fields to users.

Revision ID: 032
Revises: 031
"""

import sqlalchemy as sa
from alembic import op

revision = "032"
down_revision = "031"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "users",
        sa.Column("email_verification_token", sa.String(255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("email_verification_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("password_reset_token", sa.String(255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("password_reset_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Existing users are considered verified (backward compat)
    op.execute("UPDATE users SET email_verified = true")


def downgrade() -> None:
    op.drop_column("users", "password_reset_sent_at")
    op.drop_column("users", "password_reset_token")
    op.drop_column("users", "email_verification_sent_at")
    op.drop_column("users", "email_verification_token")
    op.drop_column("users", "email_verified")
