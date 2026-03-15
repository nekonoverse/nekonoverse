"""Storage quota service.

Provides storage usage calculation and quota checks for users.
Works with role_service to get quota limits from the user's role.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_file import DriveFile
from app.models.user import User
from app.services.role_service import get_quota_for_user


async def get_storage_usage(db: AsyncSession, user_id) -> int:
    """Return total bytes used by the user's drive files."""
    result = await db.scalar(
        select(func.coalesce(func.sum(DriveFile.size_bytes), 0)).where(
            DriveFile.owner_id == user_id,
            DriveFile.server_file.is_(False),
        )
    )
    return int(result or 0)


async def check_quota(
    db: AsyncSession, user: User, additional_bytes: int
) -> tuple[bool, int, int]:
    """Check if user can upload additional_bytes.

    Returns (ok, current_usage, quota_limit).
    quota_limit == 0 means unlimited.
    """
    quota = await get_quota_for_user(db, user)
    if quota == 0:
        # Unlimited
        usage = await get_storage_usage(db, user.id)
        return True, usage, 0

    usage = await get_storage_usage(db, user.id)
    ok = (usage + additional_bytes) <= quota
    return ok, usage, quota
