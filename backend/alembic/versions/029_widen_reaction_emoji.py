"""Widen reactions.emoji from 50 to 512 chars.

Revision ID: 029
Revises: 028
"""

from alembic import op
import sqlalchemy as sa

revision = "029"
down_revision = "028"


def upgrade() -> None:
    op.alter_column(
        "reactions",
        "emoji",
        existing_type=sa.String(50),
        type_=sa.String(512),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "reactions",
        "emoji",
        existing_type=sa.String(512),
        type_=sa.String(50),
        existing_nullable=False,
    )
