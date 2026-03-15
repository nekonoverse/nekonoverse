"""Moderator permission service — delegates to role_service.

Maintained for backward compatibility. New code should use role_service directly.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

MODERATOR_PERMISSIONS = [
    "users",
    "reports",
    "content",
    "domains",
    "federation",
    "emoji",
    "registrations",
]


async def get_moderator_permissions(db: AsyncSession) -> dict[str, bool]:
    """Return the moderator role's permission map."""
    from app.services.role_service import get_role

    role = await get_role(db, "moderator")
    if not role:
        return {perm: True for perm in MODERATOR_PERMISSIONS}
    perms = role.permissions or {}
    return {perm: perms.get(perm, True) for perm in MODERATOR_PERMISSIONS}


async def set_moderator_permissions(
    db: AsyncSession, permissions: dict[str, bool]
) -> None:
    """Update the moderator role's permission flags."""
    from app.services.role_service import get_role

    role = await get_role(db, "moderator")
    if not role:
        return
    current = dict(role.permissions) if role.permissions else {}
    for key, value in permissions.items():
        if key in MODERATOR_PERMISSIONS:
            current[key] = bool(value)
    role.permissions = current
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(role, "permissions")
    await db.commit()


async def has_moderator_permission(
    db: AsyncSession, user: User, permission: str
) -> bool:
    """Check whether user holds the given permission. Delegates to role_service."""
    from app.services.role_service import has_permission

    return await has_permission(db, user, permission)
