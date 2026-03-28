"""ストレージ容量制限サービス。

ユーザーのストレージ使用量の計算と容量制限チェックを提供する。
role_service と連携してユーザーのロールから容量制限を取得する。
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_file import DriveFile
from app.models.user import User
from app.services.role_service import get_quota_for_user


async def get_storage_usage(db: AsyncSession, user_id) -> int:
    """ユーザーのドライブファイルで使用されている合計バイト数を返す。"""
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
    """ユーザーが additional_bytes をアップロード可能か確認する。

    (ok, current_usage, quota_limit) を返す。
    quota_limit == 0 は無制限を意味する。
    """
    quota = await get_quota_for_user(db, user)
    if quota == 0:
        # 無制限
        usage = await get_storage_usage(db, user.id)
        return True, usage, 0

    usage = await get_storage_usage(db, user.id)
    ok = (usage + additional_bytes) <= quota
    return ok, usage, quota
