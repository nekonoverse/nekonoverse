"""drive_files と note_attachments にビジョンタグ付けフィールドを追加。

Revision ID: 038
Revises: 037
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "038"
down_revision = "037"


def upgrade() -> None:
    op.add_column("drive_files", sa.Column("vision_tags", JSONB, nullable=True))
    op.add_column("drive_files", sa.Column("vision_caption", sa.String(1500), nullable=True))
    op.add_column(
        "drive_files",
        sa.Column("vision_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("note_attachments", sa.Column("remote_vision_tags", JSONB, nullable=True))
    op.add_column(
        "note_attachments",
        sa.Column("remote_vision_caption", sa.String(1500), nullable=True),
    )
    op.add_column(
        "note_attachments",
        sa.Column("vision_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("note_attachments", "vision_at")
    op.drop_column("note_attachments", "remote_vision_caption")
    op.drop_column("note_attachments", "remote_vision_tags")
    op.drop_column("drive_files", "vision_at")
    op.drop_column("drive_files", "vision_caption")
    op.drop_column("drive_files", "vision_tags")
