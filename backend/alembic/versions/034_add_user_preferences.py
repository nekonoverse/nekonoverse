"""Add preferences JSONB column to users table.

Revision ID: 034
Revises: 033
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON

revision = "034"
down_revision = "033"


def upgrade() -> None:
    op.add_column("users", sa.Column("preferences", JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("users", "preferences")
