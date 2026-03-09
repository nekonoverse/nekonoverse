"""Add hashtags and note_hashtags tables

Revision ID: 015
Revises: 014
Create Date: 2026-03-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = "015"
down_revision: str = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hashtags",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(128), unique=True, nullable=False, index=True),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "last_used_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "note_hashtags",
        sa.Column(
            "note_id", UUID(as_uuid=True),
            sa.ForeignKey("notes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "hashtag_id", UUID(as_uuid=True),
            sa.ForeignKey("hashtags.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index(
        "ix_note_hashtags_hashtag_id", "note_hashtags", ["hashtag_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_note_hashtags_hashtag_id", table_name="note_hashtags")
    op.drop_table("note_hashtags")
    op.drop_table("hashtags")
