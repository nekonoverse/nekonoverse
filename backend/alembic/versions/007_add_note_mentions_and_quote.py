"""Add mentions JSONB and quote fields to notes

Revision ID: 007
Revises: 006
Create Date: 2026-03-06 14:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '007'
down_revision: Union[str, None] = '006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('notes', sa.Column('mentions', sa.JSON(), nullable=True, server_default='[]'))
    op.add_column('notes', sa.Column('quote_id', sa.UUID(), nullable=True))
    op.add_column('notes', sa.Column('quote_ap_id', sa.String(length=2048), nullable=True))
    op.create_index('ix_notes_quote_id', 'notes', ['quote_id'])
    op.create_foreign_key('fk_notes_quote_id', 'notes', 'notes', ['quote_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_notes_quote_id', 'notes', type_='foreignkey')
    op.drop_index('ix_notes_quote_id', table_name='notes')
    op.drop_column('notes', 'quote_ap_id')
    op.drop_column('notes', 'quote_id')
    op.drop_column('notes', 'mentions')
