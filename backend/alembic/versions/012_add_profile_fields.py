"""Add birthday and is_bot to actors

Revision ID: 012
Revises: 011
Create Date: 2026-03-07 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "012"
down_revision: str = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("actors", sa.Column("birthday", sa.Date(), nullable=True))
    op.add_column("actors", sa.Column("is_bot", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("actors", "is_bot")
    op.drop_column("actors", "birthday")
