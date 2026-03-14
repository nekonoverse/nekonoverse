"""Configurable moderator permission service.

Stores per-permission toggles in server_settings as a JSON blob under the key
``moderator_permissions``.  Admins always have full access; moderators are
gated by the stored flags.
"""

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

MODERATOR_PERMISSIONS = [
    "users",          # Suspend/unsuspend/silence users
    "reports",        # View/resolve/reject reports
    "content",        # Delete notes, mark sensitive
    "domains",        # Domain blocks
    "federation",     # View federation stats
    "emoji",          # Manage custom emojis
    "registrations",  # Approve/reject registrations
]


async def get_moderator_permissions(db: AsyncSession) -> dict[str, bool]:
    """Return the current moderator permission map.

    Missing keys default to ``True`` (all permissions enabled).
    """
    from app.services.server_settings_service import get_setting

    raw = await get_setting(db, "moderator_permissions")
    stored: dict[str, bool] = {}
    if raw:
        try:
            stored = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass

    # Ensure every known permission is represented, defaulting to True
    return {perm: stored.get(perm, True) for perm in MODERATOR_PERMISSIONS}


async def set_moderator_permissions(
    db: AsyncSession, permissions: dict[str, bool]
) -> None:
    """Persist moderator permission flags.

    Only known permission keys are accepted; unknown keys are silently ignored.
    """
    from app.services.server_settings_service import set_setting

    current = await get_moderator_permissions(db)
    for key, value in permissions.items():
        if key in MODERATOR_PERMISSIONS:
            current[key] = bool(value)

    await set_setting(db, "moderator_permissions", json.dumps(current))


async def has_moderator_permission(
    db: AsyncSession, user: User, permission: str
) -> bool:
    """Check whether *user* holds the given moderator permission.

    Admins always return ``True``.  Moderators are checked against the
    stored permission map.  Regular users always return ``False``.
    """
    if user.is_admin:
        return True
    if not user.is_staff:
        return False

    perms = await get_moderator_permissions(db)
    return perms.get(permission, True)
