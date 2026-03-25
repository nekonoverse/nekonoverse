"""Add focal_detect_version to drive_files and note_attachments.

Revision ID: 036
Revises: 035
"""

import sqlalchemy as sa
from alembic import op

revision = "036"
down_revision = "035"


def upgrade() -> None:
    op.add_column(
        "drive_files",
        sa.Column("focal_detect_version", sa.String(50), nullable=True),
    )
    op.add_column(
        "note_attachments",
        sa.Column("focal_detect_version", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("note_attachments", "focal_detect_version")
    op.drop_column("drive_files", "focal_detect_version")
