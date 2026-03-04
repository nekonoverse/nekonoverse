import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.user import (
    ChangePasswordRequest,
    UpdateProfileRequest,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from app.services.user_service import (
    authenticate_user,
    change_password,
    create_user,
    get_user_by_id,
    update_display_name,
)

router = APIRouter(prefix="/api/v1", tags=["auth"])

SESSION_COOKIE = "nekonoverse_session"


def get_session_id(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE)


@router.post("/accounts", response_model=UserResponse, status_code=201)
async def register(body: UserRegisterRequest, db: AsyncSession = Depends(get_db)):
    from app.config import settings

    if not settings.registration_open:
        raise HTTPException(status_code=403, detail="Registration is closed")

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

    return _user_response(user)


@router.post("/auth/login")
async def login(
    body: UserLoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    user = await authenticate_user(db, body.username, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    from app.valkey_client import valkey

    session_id = uuid.uuid4().hex
    await valkey.set(f"session:{session_id}", str(user.id), ex=86400 * 30)

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
        from app.valkey_client import valkey

        await valkey.delete(f"session:{session_id}")
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

    from app.valkey_client import valkey

    user_id_str = await valkey.get(f"session:{session_id}")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Session expired")

    user = await get_user_by_id(db, uuid.UUID(user_id_str))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return _user_response(user)


def _user_response(user: User) -> UserResponse:
    actor = user.actor
    return UserResponse(
        id=user.id,
        username=actor.username,
        display_name=actor.display_name,
        avatar_url=actor.avatar_url,
        header_url=actor.header_url,
        summary=actor.summary,
        role=user.role,
        created_at=user.created_at,
    )


@router.patch("/accounts/update_credentials", response_model=UserResponse)
async def update_credentials(
    body: UpdateProfileRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user = await update_display_name(db, user, body.display_name)
    return _user_response(user)


@router.post("/auth/change_password")
async def change_password_endpoint(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await change_password(db, user, body.current_password, body.new_password)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True}
