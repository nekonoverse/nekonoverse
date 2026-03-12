"""Add url column to notes for Web UI URL distinct from AP id.

Revision ID: 023
Revises: 022
"""

import sqlalchemy as sa
from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notes",
        sa.Column("url", sa.String(2048), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("notes", "url")
