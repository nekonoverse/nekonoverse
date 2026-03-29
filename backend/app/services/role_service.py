"""ロール管理サービス。

ロールのCRUD操作と権限チェックを提供する。
旧permission_serviceモジュールを置き換えるもの。
"""

import logging

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.role import Role
from app.models.user import User

logger = logging.getLogger(__name__)

MODERATOR_PERMISSIONS = [
    "users",
    "reports",
    "content",
    "domains",
    "federation",
    "emoji",
    "registrations",
    "announcements",
]


async def get_role(db: AsyncSession, role_name: str) -> Role | None:
    result = await db.execute(select(Role).where(Role.name == role_name))
    return result.scalar_one_or_none()


async def get_all_roles(db: AsyncSession) -> list[Role]:
    result = await db.execute(select(Role).order_by(Role.priority.desc(), Role.name))
    return list(result.scalars().all())


async def create_role(
    db: AsyncSession,
    name: str,
    display_name: str,
    copy_from: str | None = None,
) -> Role:
    existing = await get_role(db, name)
    if existing:
        raise ValueError(f"Role '{name}' already exists")

    permissions: dict = {}
    quota_bytes = 1073741824  # 1 GB default
    priority = 0

    if copy_from:
        source = await get_role(db, copy_from)
        if source:
            permissions = dict(source.permissions) if source.permissions else {}
            quota_bytes = source.quota_bytes
            priority = source.priority

    role = Role(
        name=name,
        display_name=display_name,
        permissions=permissions,
        quota_bytes=quota_bytes,
        priority=priority,
        is_system=False,
    )
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return role


async def update_role(db: AsyncSession, role_name: str, **kwargs) -> Role:
    role = await get_role(db, role_name)
    if not role:
        raise ValueError(f"Role '{role_name}' not found")

    allowed_fields = {"display_name", "permissions", "quota_bytes", "priority"}
    for key, value in kwargs.items():
        if key in allowed_fields and value is not None:
            setattr(role, key, value)

    await db.commit()
    await db.refresh(role)
    return role


async def delete_role(db: AsyncSession, role_name: str) -> None:
    role = await get_role(db, role_name)
    if not role:
        raise ValueError(f"Role '{role_name}' not found")
    if role.is_system:
        raise ValueError("Cannot delete a built-in role")

    # このロールに割り当てられているユーザーがいるか確認
    user_count = await db.scalar(
        select(func.count()).select_from(User).where(User.role == role_name)
    )
    if user_count and user_count > 0:
        raise ValueError(f"Cannot delete role '{role_name}': {user_count} user(s) assigned")

    await db.execute(delete(Role).where(Role.name == role_name))
    await db.commit()


async def has_permission(db: AsyncSession, user: User, permission: str) -> bool:
    """ロール経由でユーザーが指定権限を持っているか確認する。"""
    role = await get_role(db, user.role)
    if not role:
        return user.is_admin

    if role.is_admin:
        return True

    perms = role.permissions or {}
    return bool(perms.get(permission, False))


async def get_quota_for_user(db: AsyncSession, user: User) -> int:
    """ユーザーのロールに応じたquota_bytesを返す。0 = 無制限。"""
    role = await get_role(db, user.role)
    if not role:
        return 1073741824  # 1 GB fallback
    return role.quota_bytes


async def role_exists(db: AsyncSession, role_name: str) -> bool:
    role = await get_role(db, role_name)
    return role is not None
