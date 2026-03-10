"""Add max_uses and use_count to invitation_codes.

Revision ID: 019
Revises: 018
"""

from alembic import op
import sqlalchemy as sa

revision = "019"
down_revision = "018"


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
