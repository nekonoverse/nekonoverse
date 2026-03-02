"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-03-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # actors
    op.create_table(
        "actors",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ap_id", sa.String(2048), nullable=False),
        sa.Column("type", sa.String(50), nullable=False, server_default="Person"),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("domain", sa.String(255), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("avatar_url", sa.String(2048), nullable=True),
        sa.Column("header_url", sa.String(2048), nullable=True),
        sa.Column("inbox_url", sa.String(2048), nullable=False),
        sa.Column("outbox_url", sa.String(2048), nullable=True),
        sa.Column("shared_inbox_url", sa.String(2048), nullable=True),
        sa.Column("followers_url", sa.String(2048), nullable=True),
        sa.Column("following_url", sa.String(2048), nullable=True),
        sa.Column("public_key_pem", sa.Text(), nullable=False),
        sa.Column("is_cat", sa.Boolean(), nullable=True, server_default="false"),
        sa.Column("manually_approves_followers", sa.Boolean(), nullable=True, server_default="false"),
        sa.Column("discoverable", sa.Boolean(), nullable=True, server_default="true"),
        sa.Column("fields", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ap_id"),
        sa.UniqueConstraint("username", "domain", name="uq_actors_username_domain"),
    )
    op.create_index("ix_actors_ap_id", "actors", ["ap_id"])
    op.create_index("ix_actors_domain", "actors", ["domain"])
    op.create_index("ix_actors_domain_username", "actors", ["domain", "username"])

    # users
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("actor_id", sa.UUID(), sa.ForeignKey("actors.id"), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("private_key_pem", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("actor_id"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    # notes
    op.create_table(
        "notes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ap_id", sa.String(2048), nullable=False),
        sa.Column("actor_id", sa.UUID(), sa.ForeignKey("actors.id"), nullable=False),
        sa.Column("in_reply_to_id", sa.UUID(), sa.ForeignKey("notes.id"), nullable=True),
        sa.Column("in_reply_to_ap_id", sa.String(2048), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="public"),
        sa.Column("sensitive", sa.Boolean(), nullable=True, server_default="false"),
        sa.Column("spoiler_text", sa.String(500), nullable=True),
        sa.Column("to", postgresql.JSONB(), nullable=False),
        sa.Column("cc", postgresql.JSONB(), nullable=False),
        sa.Column("published", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replies_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("reactions_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("renotes_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("local", sa.Boolean(), nullable=False, server_default="true"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ap_id"),
    )
    op.create_index("ix_notes_ap_id", "notes", ["ap_id"])
    op.create_index("ix_notes_actor_id", "notes", ["actor_id"])
    op.create_index("ix_notes_in_reply_to_id", "notes", ["in_reply_to_id"])
    op.create_index("ix_notes_local", "notes", ["local"])
    op.create_index("ix_notes_actor_published", "notes", ["actor_id", "published"])
    op.create_index("ix_notes_local_published", "notes", ["local", "published"])

    # reactions
    op.create_table(
        "reactions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ap_id", sa.String(2048), nullable=True),
        sa.Column("actor_id", sa.UUID(), sa.ForeignKey("actors.id"), nullable=False),
        sa.Column("note_id", sa.UUID(), sa.ForeignKey("notes.id"), nullable=False),
        sa.Column("emoji", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("actor_id", "note_id", "emoji", name="uq_reactions_actor_note_emoji"),
    )
    op.create_index("ix_reactions_ap_id", "reactions", ["ap_id"], unique=True)
    op.create_index("ix_reactions_actor_id", "reactions", ["actor_id"])
    op.create_index("ix_reactions_note_id", "reactions", ["note_id"])
    op.create_index("ix_reactions_note_emoji", "reactions", ["note_id", "emoji"])

    # followers
    op.create_table(
        "followers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ap_id", sa.String(2048), nullable=True),
        sa.Column("follower_id", sa.UUID(), sa.ForeignKey("actors.id"), nullable=False),
        sa.Column("following_id", sa.UUID(), sa.ForeignKey("actors.id"), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("follower_id", "following_id", name="uq_followers_pair"),
    )
    op.create_index("ix_followers_ap_id", "followers", ["ap_id"], unique=True)
    op.create_index("ix_followers_follower", "followers", ["follower_id"])
    op.create_index("ix_followers_following", "followers", ["following_id"])

    # delivery_queue
    op.create_table(
        "delivery_queue",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), sa.ForeignKey("actors.id"), nullable=False),
        sa.Column("target_inbox_url", sa.String(2048), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_delivery_queue_status", "delivery_queue", ["status"])
    op.create_index("ix_delivery_queue_status_retry", "delivery_queue", ["status", "next_retry_at"])

    # oauth_applications
    op.create_table(
        "oauth_applications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("client_id", sa.String(255), nullable=False),
        sa.Column("client_secret", sa.String(255), nullable=False),
        sa.Column("redirect_uris", sa.Text(), nullable=False),
        sa.Column("scopes", sa.String(1024), nullable=False, server_default="read"),
        sa.Column("website", sa.String(2048), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id"),
    )
    op.create_index("ix_oauth_applications_client_id", "oauth_applications", ["client_id"])

    # oauth_authorization_codes
    op.create_table(
        "oauth_authorization_codes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(255), nullable=False),
        sa.Column("application_id", sa.UUID(), sa.ForeignKey("oauth_applications.id"), nullable=False),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("redirect_uri", sa.String(2048), nullable=False),
        sa.Column("scopes", sa.String(1024), nullable=False),
        sa.Column("code_challenge", sa.String(255), nullable=True),
        sa.Column("code_challenge_method", sa.String(10), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_oauth_authorization_codes_code", "oauth_authorization_codes", ["code"])

    # oauth_tokens
    op.create_table(
        "oauth_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("access_token", sa.String(255), nullable=False),
        sa.Column("token_type", sa.String(50), nullable=False, server_default="Bearer"),
        sa.Column("scopes", sa.String(1024), nullable=False),
        sa.Column("application_id", sa.UUID(), sa.ForeignKey("oauth_applications.id"), nullable=False),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("access_token"),
    )
    op.create_index("ix_oauth_tokens_access_token", "oauth_tokens", ["access_token"])


def downgrade() -> None:
    op.drop_table("oauth_tokens")
    op.drop_table("oauth_authorization_codes")
    op.drop_table("oauth_applications")
    op.drop_table("delivery_queue")
    op.drop_table("followers")
    op.drop_table("reactions")
    op.drop_table("notes")
    op.drop_table("users")
    op.drop_table("actors")
