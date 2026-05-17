"""TOTP リプレイ防止のため最後に成功した time-step counter を users に保存する。

RFC 6238 §5.2 に従い、同一カウンタ (および過去カウンタ) の OTP 再使用を拒否するため
の単調増加カウンタ。

Revision ID: 043
Revises: 042
"""

import sqlalchemy as sa

from alembic import op

revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_totp_counter", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "last_totp_counter")
