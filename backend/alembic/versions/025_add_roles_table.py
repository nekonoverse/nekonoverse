"""Add roles table for dynamic role management.

Creates the roles table and seeds three built-in roles (user, moderator, admin).
Migrates existing moderator_permissions from server_settings into the moderator
role's permissions JSONB column.

Revision ID: 025
Revises: 024
"""

import json

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("name", sa.String(50), primary_key=True),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("permissions", JSONB, server_default="{}", nullable=False),
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "quota_bytes", sa.BigInteger(), server_default="1073741824", nullable=False
        ),  # 1 GB
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # Widen User.role from String(20) to String(50) to accommodate custom role names
    op.alter_column("users", "role", type_=sa.String(50), existing_type=sa.String(20))

    # Read existing moderator permissions from server_settings
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT value FROM server_settings WHERE key = 'moderator_permissions'")
    ).first()
    mod_perms = {}
    if row and row[0]:
        try:
            mod_perms = json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            pass
    # Default all known permissions to True if not set
    for perm in ("users", "reports", "content", "domains", "federation", "emoji", "registrations"):
        if perm not in mod_perms:
            mod_perms[perm] = True

    # Seed built-in roles
    conn.execute(
        sa.text(
            "INSERT INTO roles (name, display_name, permissions, is_admin, quota_bytes, "
            "priority, is_system) VALUES "
            "(:n1, :d1, :p1, false, 1073741824, 0, true), "
            "(:n2, :d2, :p2, false, 5368709120, 50, true), "
            "(:n3, :d3, :p3, true, 0, 100, true)"
        ),
        {
            "n1": "user",
            "d1": "User",
            "p1": json.dumps({}),
            "n2": "moderator",
            "d2": "Moderator",
            "p2": json.dumps(mod_perms),
            "n3": "admin",
            "d3": "Admin",
            "p3": json.dumps({}),
        },
    )


def downgrade() -> None:
    # Restore User.role column width
    op.alter_column("users", "role", type_=sa.String(20), existing_type=sa.String(50))
    op.drop_table("roles")
