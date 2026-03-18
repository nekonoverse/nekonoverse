"""Add performance indexes for timeline, notification, follow, and bookmark queries.

Indexes added:
- H-8: notes(visibility, published) WHERE deleted_at IS NULL
- M-6: followers(following_id, accepted)
- M-7: notifications(type, recipient_id, sender_id, note_id) for dedup
- L-3: bookmarks(note_id)

Note: H-9 and M-5 are already covered by migration 021.

Revision ID: 027
Revises: 026
"""

import sqlalchemy as sa

from alembic import op

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # H-8: パブリックタイムラインクエリの高速化
    op.create_index(
        "ix_notes_visibility_published",
        "notes",
        ["visibility", "published"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # M-6: フォロワー取得クエリの高速化
    op.create_index(
        "ix_followers_following_accepted",
        "followers",
        ["following_id", "accepted"],
    )

    # M-7: 通知の重複チェック用インデックス
    op.create_index(
        "ix_notifications_dedup",
        "notifications",
        ["type", "recipient_id", "sender_id", "note_id"],
    )

    # L-3: ブックマークのnote_id逆引きインデックス
    op.create_index(
        "ix_bookmarks_note",
        "bookmarks",
        ["note_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_bookmarks_note", table_name="bookmarks")
    op.drop_index("ix_notifications_dedup", table_name="notifications")
    op.drop_index("ix_followers_following_accepted", table_name="followers")
    op.drop_index("ix_notes_visibility_published", table_name="notes")
