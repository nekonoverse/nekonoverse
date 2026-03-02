import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.user import UserLoginRequest, UserRegisterRequest, UserResponse
from app.services.user_service import authenticate_user, create_user, get_user_by_id

router = APIRouter(prefix="/api/v1", tags=["auth"])

SESSION_COOKIE = "nekonoverse_session"


def get_session_id(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE)


@router.post("/accounts", response_model=UserResponse, status_code=201)
async def register(body: UserRegisterRequest, db: AsyncSession = Depends(get_db)):
    try:
        user = await create_user(
            db=db,
            username=body.username,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    actor = user.actor
    return UserResponse(
        id=user.id,
        username=actor.username,
        display_name=actor.display_name,
        avatar_url=actor.avatar_url,
        header_url=actor.header_url,
        summary=actor.summary,
        created_at=user.created_at,
    )


@router.post("/auth/login")
async def login(
    body: UserLoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    user = await authenticate_user(db, body.email, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Store session in Valkey (import lazily to avoid startup issues)
    from app.valkey_client import valkey_pool

    session_id = uuid.uuid4().hex
    async with valkey_pool.client() as conn:
        await conn.set(f"session:{session_id}", str(user.id), ex=86400 * 30)

    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        samesite="lax",
        max_age=86400 * 30,
    )
    return {"ok": True}


@router.post("/auth/logout")
async def logout(request: Request, response: Response):
    session_id = get_session_id(request)
    if session_id:
        from app.valkey_client import valkey_pool

        async with valkey_pool.client() as conn:
            await conn.delete(f"session:{session_id}")
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.get("/accounts/verify_credentials", response_model=UserResponse)
async def verify_credentials(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    session_id = get_session_id(request)
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    from app.valkey_client import valkey_pool

    async with valkey_pool.client() as conn:
        user_id_str = await conn.get(f"session:{session_id}")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Session expired")

    user = await get_user_by_id(db, uuid.UUID(user_id_str))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    actor = user.actor
    return UserResponse(
        id=user.id,
        username=actor.username,
        display_name=actor.display_name,
        avatar_url=actor.avatar_url,
        header_url=actor.header_url,
        summary=actor.summary,
        created_at=user.created_at,
    )
