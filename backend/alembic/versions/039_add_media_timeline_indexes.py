"""メディアタイムライン用のパフォーマンスインデックスを追加。

Revision ID: 039
Revises: 038
"""

import sqlalchemy as sa

from alembic import op

revision = "039"
down_revision = "038"


def upgrade() -> None:
    op.create_index(
        "ix_note_attachments_remote_mime_type",
        "note_attachments",
        ["remote_mime_type"],
        postgresql_where=sa.text("remote_mime_type IS NOT NULL"),
    )
    op.create_index(
        "ix_drive_files_mime_type",
        "drive_files",
        ["mime_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_drive_files_mime_type", table_name="drive_files")
    op.drop_index("ix_note_attachments_remote_mime_type", table_name="note_attachments")
