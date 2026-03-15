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
    # OAuthベアラートークンを先にチェック
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return await get_oauth_user(request, db)

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

    # システムアカウントはセッション認証不可
    if user.is_system:
        await valkey.delete(f"session:{session_id}")
        raise HTTPException(status_code=403, detail="System accounts cannot authenticate")

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


def get_permitted_staff(permission: str):
    """Return a dependency that checks the user is admin, or moderator with
    the specified permission enabled."""

    async def dependency(
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> User:
        user = await get_current_user(request, db)
        if user.is_admin:
            return user
        if not user.is_staff:
            raise HTTPException(status_code=403, detail="Staff access required")
        from app.services.permission_service import has_moderator_permission

        if not await has_moderator_permission(db, user, permission):
            raise HTTPException(status_code=403, detail="Permission denied")
        return user

    return dependency


async def get_admin_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await get_current_user(request, db)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return user


async def get_oauth_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Authenticate a user via OAuth Bearer token (Authorization header)."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    token_str = auth_header[7:]

    import hashlib

    from sqlalchemy import select

    from app.models.oauth import OAuthToken

    # ハッシュ化トークンで検索(新方式)、見つからなければプレーンテキストで検索(互換)
    token_hash = hashlib.sha256(token_str.encode()).hexdigest()
    result = await db.execute(
        select(OAuthToken).where(OAuthToken.access_token == token_hash)
    )
    token_obj = result.scalar_one_or_none()
    if not token_obj:
        result = await db.execute(
            select(OAuthToken).where(OAuthToken.access_token == token_str)
        )
        token_obj = result.scalar_one_or_none()
    if not token_obj:
        raise HTTPException(status_code=401, detail="Invalid token")

    if token_obj.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Token revoked")

    if token_obj.is_expired:
        raise HTTPException(status_code=401, detail="Token expired")

    if not token_obj.user_id:
        raise HTTPException(status_code=401, detail="Token has no associated user")

    user = await get_user_by_id(db, token_obj.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if user.is_system:
        raise HTTPException(status_code=403, detail="System accounts cannot authenticate")

    if user.actor and user.actor.is_suspended:
        raise HTTPException(status_code=403, detail="Account is suspended")

    if user.approval_status == "pending":
        raise HTTPException(status_code=403, detail="Your registration is pending approval")

    return user


async def get_optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    # OAuthベアラートークンを先にチェック
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            return await get_oauth_user(request, db)
        except HTTPException:
            return None

    session_id = request.cookies.get("nekonoverse_session")
    if not session_id:
        return None

    from app.valkey_client import valkey

    user_id_str = await valkey.get(f"session:{session_id}")
    if not user_id_str:
        return None

    user = await get_user_by_id(db, uuid.UUID(user_id_str))
    if user and user.is_system:
        await valkey.delete(f"session:{session_id}")
        return None
    if user and user.actor and user.actor.is_suspended:
        await valkey.delete(f"session:{session_id}")
        return None
    if user and user.approval_status == "pending":
        await valkey.delete(f"session:{session_id}")
        return None

    return user
