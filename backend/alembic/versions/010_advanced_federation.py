"""Advanced federation: pinned notes, polls, account migration

Revision ID: 010
Revises: 009
Create Date: 2026-03-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Actor columns for federation
    op.add_column("actors", sa.Column("featured_url", sa.String(2048), nullable=True))
    op.add_column("actors", sa.Column("moved_to_ap_id", sa.String(2048), nullable=True))
    op.add_column("actors", sa.Column("also_known_as", postgresql.JSONB, nullable=True))

    # Note columns for polls and Misskey talk
    op.add_column("notes", sa.Column("is_poll", sa.Boolean, nullable=False, server_default="false"))
    op.add_column("notes", sa.Column("poll_options", postgresql.JSONB, nullable=True))
    op.add_column("notes", sa.Column("poll_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("notes", sa.Column("poll_multiple", sa.Boolean, nullable=False, server_default="false"))
    op.add_column("notes", sa.Column("is_talk", sa.Boolean, nullable=False, server_default="false"))

    # Pinned notes table
    op.create_table(
        "pinned_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("actors.id"), nullable=False, index=True),
        sa.Column("note_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("notes.id"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("actor_id", "note_id", name="uq_pinned_notes_actor_note"),
    )

    # Poll votes table
    op.create_table(
        "poll_votes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("note_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("notes.id"), nullable=False, index=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("actors.id"), nullable=False),
        sa.Column("choice_index", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("note_id", "actor_id", "choice_index",
                            name="uq_poll_votes_note_actor_choice"),
    )


def downgrade() -> None:
    op.drop_table("poll_votes")
    op.drop_table("pinned_notes")

    op.drop_column("notes", "is_talk")
    op.drop_column("notes", "poll_multiple")
    op.drop_column("notes", "poll_expires_at")
    op.drop_column("notes", "poll_options")
    op.drop_column("notes", "is_poll")

    op.drop_column("actors", "also_known_as")
    op.drop_column("actors", "moved_to_ap_id")
    op.drop_column("actors", "featured_url")
