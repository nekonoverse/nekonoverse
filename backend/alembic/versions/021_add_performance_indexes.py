"""Add performance indexes for common query patterns.

Revision ID: 021
Revises: 020
"""

from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # notifications: pagination by (recipient_id, created_at DESC)
    op.create_index(
        "ix_notifications_recipient_created",
        "notifications",
        ["recipient_id", "created_at"],
        postgresql_ops={"created_at": "DESC"},
    )
    # notifications: bulk mark-as-read by (recipient_id, read)
    op.create_index(
        "ix_notifications_recipient_read",
        "notifications",
        ["recipient_id", "read"],
    )
    # bookmarks: pagination by (actor_id, created_at DESC)
    op.create_index(
        "ix_bookmarks_actor_created",
        "bookmarks",
        ["actor_id", "created_at"],
        postgresql_ops={"created_at": "DESC"},
    )
    # poll_votes: duplicate vote check by actor
    op.create_index(
        "ix_poll_votes_actor",
        "poll_votes",
        ["actor_id"],
    )
    # user_blocks: reverse lookup (who blocked this target)
    op.create_index(
        "ix_user_blocks_target",
        "user_blocks",
        ["target_id"],
    )
    # user_mutes: reverse lookup (who muted this target)
    op.create_index(
        "ix_user_mutes_target",
        "user_mutes",
        ["target_id"],
    )
    # note_attachments: join on drive_file_id
    op.create_index(
        "ix_note_attachments_drive_file",
        "note_attachments",
        ["drive_file_id"],
    )
    # reports: lookup by reporter
    op.create_index(
        "ix_reports_reporter_actor",
        "reports",
        ["reporter_actor_id"],
    )
    # reports: lookup by target note
    op.create_index(
        "ix_reports_target_note",
        "reports",
        ["target_note_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_reports_target_note", table_name="reports")
    op.drop_index("ix_reports_reporter_actor", table_name="reports")
    op.drop_index("ix_note_attachments_drive_file", table_name="note_attachments")
    op.drop_index("ix_user_mutes_target", table_name="user_mutes")
    op.drop_index("ix_user_blocks_target", table_name="user_blocks")
    op.drop_index("ix_poll_votes_actor", table_name="poll_votes")
    op.drop_index("ix_bookmarks_actor_created", table_name="bookmarks")
    op.drop_index("ix_notifications_recipient_read", table_name="notifications")
    op.drop_index("ix_notifications_recipient_created", table_name="notifications")
