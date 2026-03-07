"""Expand custom_emojis: aliases, license, CherryPick fields, drive_file_id

Revision ID: 011
Revises: 010
Create Date: 2026-03-07 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Misskey-compatible fields
    op.add_column("custom_emojis", sa.Column("aliases", postgresql.JSONB(), nullable=True))
    op.add_column("custom_emojis", sa.Column("license", sa.String(1024), nullable=True))
    op.add_column("custom_emojis", sa.Column("is_sensitive", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("custom_emojis", sa.Column("local_only", sa.Boolean(), nullable=False, server_default="false"))

    # CherryPick (yojo-art) fields
    op.add_column("custom_emojis", sa.Column("author", sa.String(128), nullable=True))
    op.add_column("custom_emojis", sa.Column("description", sa.String(512), nullable=True))
    op.add_column("custom_emojis", sa.Column("copy_permission", sa.String(20), nullable=True))
    op.add_column("custom_emojis", sa.Column("usage_info", sa.String(512), nullable=True))
    op.add_column("custom_emojis", sa.Column("is_based_on", sa.String(1024), nullable=True))
    op.add_column("custom_emojis", sa.Column("import_from", sa.String(1024), nullable=True))

    # Link to DriveFile for local emoji images
    op.add_column("custom_emojis", sa.Column(
        "drive_file_id", sa.UUID(),
        sa.ForeignKey("drive_files.id", ondelete="SET NULL"),
        nullable=True,
    ))


def downgrade() -> None:
    op.drop_column("custom_emojis", "drive_file_id")
    op.drop_column("custom_emojis", "import_from")
    op.drop_column("custom_emojis", "is_based_on")
    op.drop_column("custom_emojis", "usage_info")
    op.drop_column("custom_emojis", "copy_permission")
    op.drop_column("custom_emojis", "description")
    op.drop_column("custom_emojis", "author")
    op.drop_column("custom_emojis", "local_only")
    op.drop_column("custom_emojis", "is_sensitive")
    op.drop_column("custom_emojis", "license")
    op.drop_column("custom_emojis", "aliases")
