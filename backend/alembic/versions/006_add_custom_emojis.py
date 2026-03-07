"""Add custom_emojis table

Revision ID: 006
Revises: 005
Create Date: 2026-03-06 14:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '006'
down_revision: Union[str, None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'custom_emojis',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('shortcode', sa.String(length=100), nullable=False),
        sa.Column('domain', sa.String(length=255), nullable=True),
        sa.Column('url', sa.String(length=2048), nullable=False),
        sa.Column('static_url', sa.String(length=2048), nullable=True),
        sa.Column('visible_in_picker', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('category', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('shortcode', 'domain', name='uq_custom_emojis_shortcode_domain'),
    )
    op.create_index('ix_custom_emojis_domain', 'custom_emojis', ['domain'])
    op.create_index('ix_custom_emojis_shortcode_domain', 'custom_emojis', ['shortcode', 'domain'])


def downgrade() -> None:
    op.drop_index('ix_custom_emojis_shortcode_domain', table_name='custom_emojis')
    op.drop_index('ix_custom_emojis_domain', table_name='custom_emojis')
    op.drop_table('custom_emojis')
