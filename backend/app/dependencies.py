import uuid
from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.user import User
from app.services.user_service import get_user_by_id


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    session_id = request.cookies.get("nekonoverse_session")
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    from app.valkey_client import valkey

    user_id_str = await valkey.get(f"session:{session_id}")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Session expired")

    user = await get_user_by_id(db, uuid.UUID(user_id_str))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Deny access if the user's actor has been suspended
    if user.actor and user.actor.is_suspended:
        # Invalidate this session so the client does not retry
        await valkey.delete(f"session:{session_id}")
        raise HTTPException(status_code=403, detail="Account is suspended")

    # 承認待ちユーザーはアクセス不可
    if user.approval_status == "pending":
        await valkey.delete(f"session:{session_id}")
        raise HTTPException(status_code=403, detail="Your registration is pending approval")

    return user


async def get_staff_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await get_current_user(request, db)
    if not user.is_staff:
        raise HTTPException(status_code=403, detail="Staff only")
    return user


async def get_admin_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await get_current_user(request, db)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return user


async def get_optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    session_id = request.cookies.get("nekonoverse_session")
    if not session_id:
        return None

    from app.valkey_client import valkey

    user_id_str = await valkey.get(f"session:{session_id}")
    if not user_id_str:
        return None

    user = await get_user_by_id(db, uuid.UUID(user_id_str))
    if user and user.actor and user.actor.is_suspended:
        await valkey.delete(f"session:{session_id}")
        return None
    if user and user.approval_status == "pending":
        await valkey.delete(f"session:{session_id}")
        return None

    return user
