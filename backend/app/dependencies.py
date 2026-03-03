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

    return await get_user_by_id(db, uuid.UUID(user_id_str))
