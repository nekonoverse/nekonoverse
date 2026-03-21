"""Sanitize existing emoji shortcodes: replace hyphens and other
invalid characters with underscores.

Revision ID: 031
Revises: 030
"""

from alembic import op

revision = "031"
down_revision = "030"


def upgrade() -> None:
    # Replace any non-alphanumeric/underscore character with underscore
    op.execute(
        "UPDATE custom_emojis "
        "SET shortcode = regexp_replace(shortcode, '[^a-zA-Z0-9_]', '_', 'g') "
        "WHERE shortcode ~ '[^a-zA-Z0-9_]'"
    )


def downgrade() -> None:
    # Data migration — cannot be reversed
    pass
