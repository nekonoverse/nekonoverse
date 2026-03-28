import asyncio
import uuid

import bcrypt as _bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.actor import Actor
from app.models.user import User
from app.utils.crypto import generate_rsa_keypair

# ユーザー登録で使用できない予約語（すべて小文字で比較）
RESERVED_USERNAMES: frozenset[str] = frozenset({
    # システム関連
    "system", "nekonoverse", "admin", "administrator", "moderator",
    "instance", "relay", "root",
    # ActivityPub関連
    "actor", "inbox", "outbox", "followers", "following",
    "featured", "collections",
    # ルーティング衝突
    "api", "auth", "oauth", "media", "users", "notes",
    "notifications", "settings", "about", "search", "explore",
    "tags", "nodeinfo", "well_known",
    # なりすまし防止
    "support", "help", "security", "abuse",
    "postmaster", "webmaster", "noreply", "no_reply",
})


def is_reserved_username(username: str) -> bool:
    """ユーザー名が予約語かどうかを確認する (大文字小文字を区別しない)。"""
    return username.lower() in RESERVED_USERNAMES


async def create_user(
    db: AsyncSession,
    username: str,
    email: str,
    password: str,
    display_name: str | None = None,
    role: str = "user",
    approval_status: str = "approved",
    registration_reason: str | None = None,
    skip_reserved_check: bool = False,
) -> User:
    username = username.lower()
    if not skip_reserved_check and is_reserved_username(username):
        raise ValueError("This username is reserved")
    # ユーザー名またはメールアドレスが既に存在するか確認
    existing_actor = await db.execute(
        select(Actor).where(Actor.username == username, Actor.domain.is_(None))
    )
    if existing_actor.scalar_one_or_none():
        raise ValueError("Username or email is already in use")

    existing_email = await db.execute(select(User).where(User.email == email))
    if existing_email.scalar_one_or_none():
        raise ValueError("Username or email is already in use")

    # RSA鍵ペアを生成
    private_pem, public_pem = generate_rsa_keypair()

    # アクターを作成
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

    # ユーザーを作成
    user = User(
        email=email,
        password_hash=(
            await asyncio.to_thread(_bcrypt.hashpw, password.encode(), _bcrypt.gensalt())
        ).decode(),
        actor_id=actor_id,
        role=role,
        private_key_pem=private_pem,
        approval_status=approval_status,
        registration_reason=registration_reason,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await db.refresh(actor)

    return user


async def authenticate_user(db: AsyncSession, username: str, password: str) -> User | None:
    # タイミング差によるユーザー列挙を防ぐためのダミーハッシュ
    _dummy_hash = b"$2b$12$LJ3m4ys3Lg2VEqGOAOPMb.5Q9MQhRr0vIIfSCpOIYXJDkJp0wqvN6"
    result = await db.execute(
        select(Actor).where(Actor.username == username.lower(), Actor.domain.is_(None))
    )
    actor = result.scalar_one_or_none()
    if actor is None or actor.local_user is None:
        await asyncio.to_thread(_bcrypt.checkpw, password.encode(), _dummy_hash)
        return None
    user = actor.local_user
    # システムアカウントはログイン不可
    if user.is_system:
        await asyncio.to_thread(_bcrypt.checkpw, password.encode(), _dummy_hash)
        return None
    valid = await asyncio.to_thread(_bcrypt.checkpw, password.encode(), user.password_hash.encode())
    if not valid:
        return None
    return user


async def reset_password(db: AsyncSession, username: str, new_password: str) -> User:
    result = await db.execute(
        select(Actor).where(Actor.username == username.lower(), Actor.domain.is_(None))
    )
    actor = result.scalar_one_or_none()
    if actor is None or actor.local_user is None:
        raise ValueError(f"User not found: {username}")
    user = actor.local_user
    # システムアカウントのパスワードリセットを拒否
    if user.is_system:
        raise ValueError("Cannot reset password for system account")
    user.password_hash = (
        await asyncio.to_thread(_bcrypt.hashpw, new_password.encode(), _bcrypt.gensalt())
    ).decode()
    await db.commit()
    await db.refresh(user)
    return user


async def update_display_name(db: AsyncSession, user: User, display_name: str | None) -> User:
    user.actor.display_name = display_name
    await db.commit()
    await db.refresh(user)
    await db.refresh(user.actor)
    return user


async def change_password(
    db: AsyncSession, user: User, current_password: str, new_password: str
) -> User:
    valid = await asyncio.to_thread(
        _bcrypt.checkpw,
        current_password.encode(),
        user.password_hash.encode(),
    )
    if not valid:
        raise ValueError("Current password is incorrect")
    user.password_hash = (
        await asyncio.to_thread(_bcrypt.hashpw, new_password.encode(), _bcrypt.gensalt())
    ).decode()
    await db.commit()
    await db.refresh(user)
    return user


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(User).where(User.id == user_id).options(selectinload(User.actor))
    )
    return result.scalar_one_or_none()
