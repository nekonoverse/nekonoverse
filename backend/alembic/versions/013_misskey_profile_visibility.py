"""Add Misskey profile visibility fields to actors

Revision ID: 013
Revises: 012
Create Date: 2026-03-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "013"
down_revision: str = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("actors", sa.Column("require_signin_to_view", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("actors", sa.Column("make_notes_followers_only_before", sa.BigInteger(), nullable=True))
    op.add_column("actors", sa.Column("make_notes_hidden_before", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("actors", "make_notes_hidden_before")
    op.drop_column("actors", "make_notes_followers_only_before")
    op.drop_column("actors", "require_signin_to_view")
