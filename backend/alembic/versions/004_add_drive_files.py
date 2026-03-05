"""Add drive_files table and avatar/header FK columns to actors

Revision ID: 004
Revises: 003
Create Date: 2026-03-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "drive_files",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "owner_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("s3_key", sa.String(1024), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(127), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("blurhash", sa.String(100), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("description", sa.String(1500), nullable=True),
        sa.Column("server_file", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("s3_key"),
    )
    op.create_index("ix_drive_files_owner_id", "drive_files", ["owner_id"])
    op.create_index("ix_drive_files_owner_created", "drive_files", ["owner_id", "created_at"])

    op.add_column("actors", sa.Column(
        "avatar_file_id", sa.UUID(),
        sa.ForeignKey("drive_files.id", ondelete="SET NULL"),
        nullable=True,
    ))
    op.add_column("actors", sa.Column(
        "header_file_id", sa.UUID(),
        sa.ForeignKey("drive_files.id", ondelete="SET NULL"),
        nullable=True,
    ))


def downgrade() -> None:
    op.drop_column("actors", "header_file_id")
    op.drop_column("actors", "avatar_file_id")
    op.drop_index("ix_drive_files_owner_created", table_name="drive_files")
    op.drop_index("ix_drive_files_owner_id", table_name="drive_files")
    op.drop_table("drive_files")
