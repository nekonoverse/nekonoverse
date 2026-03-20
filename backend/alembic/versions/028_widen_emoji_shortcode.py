"""Widen custom_emojis.shortcode from 100 to 255 chars.

Revision ID: 028
Revises: 027
"""

from alembic import op
import sqlalchemy as sa

revision = "028"
down_revision = "027"


def upgrade() -> None:
    op.alter_column(
        "custom_emojis",
        "shortcode",
        existing_type=sa.String(100),
        type_=sa.String(255),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "custom_emojis",
        "shortcode",
        existing_type=sa.String(255),
        type_=sa.String(100),
        existing_nullable=False,
    )
