"""アカウント削除用フィールドを追加。

Revision ID: 040
Revises: 039
"""

import sqlalchemy as sa

from alembic import op

revision = "040"
down_revision = "039"


def upgrade() -> None:
    op.add_column("actors", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "actors", sa.Column("deletion_scheduled_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_actors_deletion_scheduled",
        "actors",
        ["deletion_scheduled_at"],
        postgresql_where=sa.text("deletion_scheduled_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_actors_deletion_scheduled", table_name="actors")
    op.drop_column("actors", "deletion_scheduled_at")
    op.drop_column("actors", "deleted_at")
