"""Add note_attachments table

Revision ID: 005
Revises: aa300feab859
Create Date: 2026-03-06 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '005'
down_revision: Union[str, None] = 'aa300feab859'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'note_attachments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('note_id', sa.UUID(), nullable=False),
        sa.Column('drive_file_id', sa.UUID(), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('remote_url', sa.String(length=2048), nullable=True),
        sa.Column('remote_mime_type', sa.String(length=127), nullable=True),
        sa.Column('remote_name', sa.String(length=255), nullable=True),
        sa.Column('remote_blurhash', sa.String(length=100), nullable=True),
        sa.Column('remote_width', sa.Integer(), nullable=True),
        sa.Column('remote_height', sa.Integer(), nullable=True),
        sa.Column('remote_description', sa.String(length=1500), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['note_id'], ['notes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['drive_file_id'], ['drive_files.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_note_attachments_note_id', 'note_attachments', ['note_id'])


def downgrade() -> None:
    op.drop_index('ix_note_attachments_note_id', table_name='note_attachments')
    op.drop_table('note_attachments')
