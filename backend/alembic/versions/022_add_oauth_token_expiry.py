"""Add expires_at column to oauth_tokens.

Revision ID: 022
Revises: 021
"""

import sqlalchemy as sa
from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "oauth_tokens",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("oauth_tokens", "expires_at")
