"""動画サムネイル用フィールドを追加。

Revision ID: 041
Revises: 040
"""

import sqlalchemy as sa

from alembic import op

revision = "041"
down_revision = "040"


def upgrade() -> None:
    op.add_column(
        "drive_files", sa.Column("thumbnail_s3_key", sa.String(1024), nullable=True)
    )
    op.add_column(
        "drive_files", sa.Column("thumbnail_mime_type", sa.String(127), nullable=True)
    )
    op.add_column("drive_files", sa.Column("duration", sa.Float, nullable=True))

    op.add_column(
        "note_attachments", sa.Column("remote_thumbnail_url", sa.String(2048), nullable=True)
    )
    op.add_column(
        "note_attachments",
        sa.Column("remote_thumbnail_mime_type", sa.String(127), nullable=True),
    )
    op.add_column("note_attachments", sa.Column("remote_duration", sa.Float, nullable=True))


def downgrade() -> None:
    op.drop_column("note_attachments", "remote_duration")
    op.drop_column("note_attachments", "remote_thumbnail_mime_type")
    op.drop_column("note_attachments", "remote_thumbnail_url")
    op.drop_column("drive_files", "duration")
    op.drop_column("drive_files", "thumbnail_mime_type")
    op.drop_column("drive_files", "thumbnail_s3_key")
