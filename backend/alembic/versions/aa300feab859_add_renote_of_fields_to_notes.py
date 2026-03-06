"""Add renote_of fields to notes

Revision ID: aa300feab859
Revises: 004
Create Date: 2026-03-06 12:33:12.789689

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aa300feab859'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('notes', sa.Column('renote_of_id', sa.UUID(), nullable=True))
    op.add_column('notes', sa.Column('renote_of_ap_id', sa.String(length=2048), nullable=True))
    op.create_index(op.f('ix_notes_renote_of_id'), 'notes', ['renote_of_id'], unique=False)
    op.create_foreign_key('fk_notes_renote_of_id', 'notes', 'notes', ['renote_of_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_notes_renote_of_id', 'notes', type_='foreignkey')
    op.drop_index(op.f('ix_notes_renote_of_id'), table_name='notes')
    op.drop_column('notes', 'renote_of_ap_id')
    op.drop_column('notes', 'renote_of_id')
