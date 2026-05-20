"""actors の inbox_url / shared_inbox_url index を CREATE INDEX CONCURRENTLY 化する。

issue #1042: 044 で追加した通常 index を drop し、CONCURRENTLY で再作成する。
大規模 instance (actors 10 万行+) における migration の ACCESS EXCLUSIVE
ロック時間を SHARE UPDATE EXCLUSIVE に抑え、配送・WebFinger 等の actors
読み取りを邪魔せず index 構築できるようにする。

注意:
- CONCURRENTLY は transaction 外で実行する必要があるため autocommit_block でラップ。
- migration が中断すると INVALID index が残る可能性 (Postgres 仕様)。
  リカバリ手順は docs/deploy.md を参照。
- CI は Base.metadata.create_all で初期化するため、本 migration は CI で走らない。
  ローカルの `alembic upgrade head` / `downgrade -1` 往復で検証すること。

Revision ID: 045
Revises: 044
"""

import sqlalchemy as sa

from alembic import op

revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        # drop は CONCURRENTLY + IF EXISTS で冪等。中断で INVALID index が
        # 残った状態で再 apply されても、ここで INVALID も含めて巻き取られる。
        op.drop_index(
            "ix_actors_inbox_url",
            table_name="actors",
            postgresql_concurrently=True,
            if_exists=True,
        )
        op.drop_index(
            "ix_actors_shared_inbox_url",
            table_name="actors",
            postgresql_concurrently=True,
            if_exists=True,
        )
        op.create_index(
            "ix_actors_inbox_url",
            "actors",
            ["inbox_url"],
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_actors_shared_inbox_url",
            "actors",
            ["shared_inbox_url"],
            postgresql_concurrently=True,
            postgresql_where=sa.text("shared_inbox_url IS NOT NULL"),
        )


def downgrade() -> None:
    # 巻き戻しでも ACCESS EXCLUSIVE を取らないよう、再作成も CONCURRENTLY で行う。
    # 044 とは index 種別が同等 (機能的に同一の B-tree) なので、運用上 044 完全一致
    # である必要はない。drop/create の順序は upgrade と揃える (inbox_url → shared)。
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_actors_inbox_url",
            table_name="actors",
            postgresql_concurrently=True,
            if_exists=True,
        )
        op.drop_index(
            "ix_actors_shared_inbox_url",
            table_name="actors",
            postgresql_concurrently=True,
            if_exists=True,
        )
        op.create_index(
            "ix_actors_inbox_url",
            "actors",
            ["inbox_url"],
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_actors_shared_inbox_url",
            "actors",
            ["shared_inbox_url"],
            postgresql_concurrently=True,
            postgresql_where=sa.text("shared_inbox_url IS NOT NULL"),
        )
