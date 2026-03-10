"""Add focal point columns to drive_files and note_attachments

Revision ID: 018
Revises: 017
Create Date: 2026-03-10
"""

import sqlalchemy as sa

from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "drive_files",
        sa.Column("focal_x", sa.Float(), nullable=True),
    )
    op.add_column(
        "drive_files",
        sa.Column("focal_y", sa.Float(), nullable=True),
    )
    op.add_column(
        "note_attachments",
        sa.Column("remote_focal_x", sa.Float(), nullable=True),
    )
    op.add_column(
        "note_attachments",
        sa.Column("remote_focal_y", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("note_attachments", "remote_focal_y")
    op.drop_column("note_attachments", "remote_focal_x")
    op.drop_column("drive_files", "focal_y")
    op.drop_column("drive_files", "focal_x")
