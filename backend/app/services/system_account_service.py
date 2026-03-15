"""Service for managing system accounts (instance.actor, etc.)."""

import logging
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.actor import Actor
from app.models.user import User
from app.utils.crypto import generate_rsa_keypair

logger = logging.getLogger(__name__)

# システムアカウント定義
SYSTEM_ACCOUNTS = [
    {
        "username": "instance.actor",
        "display_name": "Instance Actor",
    },
]


async def ensure_system_account(
    db: AsyncSession,
    username: str,
    display_name: str,
) -> User:
    """Create a system account if it does not already exist. Idempotent."""
    result = await db.execute(
        select(Actor).where(Actor.username == username, Actor.domain.is_(None))
    )
    actor = result.scalar_one_or_none()
    if actor and actor.local_user:
        return actor.local_user

    private_pem, public_pem = generate_rsa_keypair()

    actor_id = uuid.uuid4()
    ap_id = f"{settings.server_url}/users/{username}"
    actor = Actor(
        id=actor_id,
        ap_id=ap_id,
        type="Application",
        username=username,
        domain=None,
        display_name=display_name,
        inbox_url=f"{ap_id}/inbox",
        outbox_url=f"{ap_id}/outbox",
        shared_inbox_url=f"{settings.server_url}/inbox",
        followers_url=f"{ap_id}/followers",
        following_url=f"{ap_id}/following",
        public_key_pem=public_pem,
        is_bot=True,
        discoverable=False,
    )
    db.add(actor)

    # システムアカウントはログイン不可のためランダムパスワードとダミーメールを使用
    user = User(
        email=f"{username}@system.internal",
        password_hash=secrets.token_hex(32),
        actor_id=actor_id,
        role="admin",
        is_system=True,
        private_key_pem=private_pem,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await db.refresh(actor)

    logger.info("Created system account: %s", username)
    return user


async def ensure_system_accounts(db: AsyncSession) -> None:
    """Ensure all required system accounts exist. Called on startup."""
    for account in SYSTEM_ACCOUNTS:
        await ensure_system_account(db, account["username"], account["display_name"])


async def get_system_account(db: AsyncSession, username: str) -> User | None:
    """Get a system account by username."""
    result = await db.execute(
        select(Actor).where(Actor.username == username, Actor.domain.is_(None))
    )
    actor = result.scalar_one_or_none()
    if not actor or not actor.local_user or not actor.local_user.is_system:
        return None
    return actor.local_user


async def get_instance_actor(db: AsyncSession) -> User | None:
    """Get the instance.actor system account."""
    return await get_system_account(db, "instance.actor")
