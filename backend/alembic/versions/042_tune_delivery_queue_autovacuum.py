"""delivery_queue の autovacuum を攻める設定に変更。

delivery_queue は status 遷移 (pending→processing→delivered/dead) と
next_retry_at 更新で UPDATE が多い。デフォルトの vacuum_scale_factor=0.2 だと
30k 行で 6k 行の dead tuple が溜まるまで起動せず bloat が進行する。
5% まで下げて遅延を小さくする。

Revision ID: 042
Revises: 041
"""

from alembic import op

revision = "042"
down_revision = "041"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE delivery_queue SET ("
        "autovacuum_vacuum_scale_factor = 0.05, "
        "autovacuum_analyze_scale_factor = 0.05"
        ")"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE delivery_queue RESET ("
        "autovacuum_vacuum_scale_factor, "
        "autovacuum_analyze_scale_factor"
        ")"
    )
