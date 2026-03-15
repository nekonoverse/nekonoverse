"""Add is_system flag to users table for system accounts.

Revision ID: 024
Revises: 023
"""

import sqlalchemy as sa

from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index(
        "ix_users_is_system",
        "users",
        ["is_system"],
        postgresql_where=sa.text("is_system = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_users_is_system", table_name="users")
    op.drop_column("users", "is_system")
