"""Add approval_status and registration_reason to users table.

Revision ID: 020
Revises: 019
"""

import sqlalchemy as sa
from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "approval_status",
            sa.String(20),
            nullable=False,
            server_default="approved",
        ),
    )
    op.add_column(
        "users",
        sa.Column("registration_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "registration_reason")
    op.drop_column("users", "approval_status")
