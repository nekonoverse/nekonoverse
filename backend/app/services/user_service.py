import uuid

import bcrypt as _bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.actor import Actor
from app.models.user import User
from app.utils.crypto import generate_rsa_keypair


async def create_user(
    db: AsyncSession,
    username: str,
    email: str,
    password: str,
    display_name: str | None = None,
    role: str = "user",
) -> User:
    # Check if username or email already exists
    existing_actor = await db.execute(
        select(Actor).where(Actor.username == username, Actor.domain.is_(None))
    )
    if existing_actor.scalar_one_or_none():
        raise ValueError("Username already taken")

    existing_email = await db.execute(select(User).where(User.email == email))
    if existing_email.scalar_one_or_none():
        raise ValueError("Email already registered")

    # Generate RSA key pair
    private_pem, public_pem = generate_rsa_keypair()

    # Create actor
    actor_id = uuid.uuid4()
    ap_id = f"{settings.server_url}/users/{username}"
    actor = Actor(
        id=actor_id,
        ap_id=ap_id,
        type="Person",
        username=username,
        domain=None,
        display_name=display_name or username,
        inbox_url=f"{ap_id}/inbox",
        outbox_url=f"{ap_id}/outbox",
        shared_inbox_url=f"{settings.server_url}/inbox",
        followers_url=f"{ap_id}/followers",
        following_url=f"{ap_id}/following",
        public_key_pem=public_pem,
    )
    db.add(actor)

    # Create user
    user = User(
        email=email,
        password_hash=_bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode(),
        actor_id=actor_id,
        role=role,
        private_key_pem=private_pem,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await db.refresh(actor)

    return user


async def authenticate_user(db: AsyncSession, username: str, password: str) -> User | None:
    result = await db.execute(
        select(Actor).where(Actor.username == username, Actor.domain.is_(None))
    )
    actor = result.scalar_one_or_none()
    if actor is None or actor.local_user is None:
        return None
    user = actor.local_user
    if not _bcrypt.checkpw(password.encode(), user.password_hash.encode()):
        return None
    return user


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()
