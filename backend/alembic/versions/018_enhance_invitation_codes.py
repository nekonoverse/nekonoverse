"""Add max_uses and use_count to invitation_codes.

Revision ID: 018
Revises: 017
"""

from alembic import op
import sqlalchemy as sa

revision = "018"
down_revision = "017"


def upgrade() -> None:
    op.add_column(
        "invitation_codes",
        sa.Column("max_uses", sa.Integer(), nullable=True, server_default="1"),
    )
    op.add_column(
        "invitation_codes",
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("invitation_codes", "use_count")
    op.drop_column("invitation_codes", "max_uses")
