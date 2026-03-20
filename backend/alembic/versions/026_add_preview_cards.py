"""Add preview_cards table for URL preview / link card data.

Revision ID: 026
Revises: 025
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "preview_cards",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "note_id",
            UUID(as_uuid=True),
            sa.ForeignKey("notes.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("image", sa.String(2048), nullable=True),
        sa.Column("site_name", sa.String(200), nullable=True),
        sa.Column("card_type", sa.String(20), nullable=False, server_default="link"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_preview_cards_note_id", "preview_cards", ["note_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_preview_cards_note_id", table_name="preview_cards")
    op.drop_table("preview_cards")
