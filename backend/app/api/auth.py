import asyncio
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.user import (
    ChangePasswordRequest,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from app.services.user_service import (
    authenticate_user,
    change_password,
    create_user,
    update_display_name,
)

router = APIRouter(prefix="/api/v1", tags=["auth"])

SESSION_COOKIE = "nekonoverse_session"
TOTP_TOKEN_TTL = 300  # 5 minutes
TOTP_MAX_ATTEMPTS = 5
TOTP_LOCKOUT_TTL = 300  # 5 minutes


def get_session_id(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE)


@router.post("/accounts", response_model=UserResponse, status_code=201)
async def register(body: UserRegisterRequest, db: AsyncSession = Depends(get_db)):
    from app.config import settings
    from app.services.server_settings_service import get_setting

    # Determine registration mode
    mode_setting = await get_setting(db, "registration_mode")
    if mode_setting is not None:
        mode = mode_setting
    else:
        # Fallback to legacy registration_open setting
        reg_setting = await get_setting(db, "registration_open")
        reg_open = (
            (reg_setting == "true") if reg_setting is not None
            else settings.registration_open
        )
        mode = "open" if reg_open else "closed"

    if mode == "closed":
        raise HTTPException(status_code=403, detail="Registration is closed")

    # Validate invite code when in invite mode
    invite = None
    if mode == "invite":
        if not body.invite_code:
            raise HTTPException(
                status_code=422, detail="Invitation code is required",
            )
        from app.services.invitation_service import validate_invitation_code
        invite = await validate_invitation_code(db, body.invite_code)
        if invite is None:
            raise HTTPException(
                status_code=422,
                detail="Invalid or expired invitation code",
            )

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

    # Redeem invite code after successful user creation
    if invite:
        from app.services.invitation_service import redeem_invitation
        await redeem_invitation(db, invite, user)
        await db.commit()

    return _user_response(user)


@router.post("/auth/login")
async def login(
    body: UserLoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    user = await authenticate_user(db, body.username, body.password)
    if user is None:
        raise HTTPException(
            status_code=401, detail="Invalid username or password",
        )

    # If TOTP is enabled, return a temporary token instead of a session
    if user.totp_enabled:
        from app.valkey_client import valkey

        totp_token = uuid.uuid4().hex
        await valkey.set(
            f"totp_pending:{totp_token}",
            str(user.id),
            ex=TOTP_TOKEN_TTL,
        )
        return {"requires_totp": True, "totp_token": totp_token}

    from app.valkey_client import valkey

    session_id = uuid.uuid4().hex
    await valkey.set(f"session:{session_id}", str(user.id), ex=86400 * 30)

    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        secure=settings.use_https,
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
    user: User = Depends(get_current_user),
):
    return _user_response(user)


DEFAULT_AVATAR_PATH = "/default-avatar.svg"


def _user_response(user: User) -> UserResponse:
    actor = user.actor
    return UserResponse(
        id=user.id,
        username=actor.username,
        display_name=actor.display_name,
        avatar_url=actor.avatar_url or DEFAULT_AVATAR_PATH,
        header_url=actor.header_url,
        summary=actor.summary,
        fields=actor.fields or [],
        birthday=actor.birthday,
        is_cat=actor.is_cat,
        is_bot=actor.is_bot,
        locked=actor.manually_approves_followers,
        discoverable=actor.discoverable,
        role=user.role,
        created_at=user.created_at,
    )


@router.patch("/accounts/update_credentials", response_model=UserResponse)
async def update_credentials(
    display_name: str | None = Form(None),
    summary: str | None = Form(None),
    fields_attributes: str | None = Form(None),
    birthday: str | None = Form(None),
    is_cat: bool | None = Form(None),
    is_bot: bool | None = Form(None),
    locked: bool | None = Form(None),
    discoverable: bool | None = Form(None),
    avatar: UploadFile | None = File(None),
    header: UploadFile | None = File(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    changed = False

    if display_name is not None:
        user = await update_display_name(db, user, display_name or None)
        changed = True

    if summary is not None:
        from app.utils.sanitize import text_to_html
        user.actor.summary = text_to_html(summary) if summary else None
        changed = True

    if fields_attributes is not None:
        import json as _json

        import bleach as _bleach
        try:
            fields_list = _json.loads(fields_attributes)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=422, detail="Invalid fields JSON",
            )
        if not isinstance(fields_list, list) or len(fields_list) > 4:
            raise HTTPException(
                status_code=422, detail="Maximum 4 fields allowed",
            )
        validated = []
        for f in fields_list:
            if not isinstance(f, dict):
                continue
            name = _bleach.clean(str(f.get("name", "")))[:255]
            value = _bleach.clean(str(f.get("value", "")))[:2048]
            if name or value:
                validated.append({"name": name, "value": value})
        user.actor.fields = validated
        changed = True

    if birthday is not None:
        if birthday == "":
            user.actor.birthday = None
        else:
            import datetime as _dt
            try:
                user.actor.birthday = _dt.date.fromisoformat(birthday)
            except ValueError:
                raise HTTPException(
                    status_code=422, detail="Invalid date format",
                )
        changed = True

    if is_cat is not None:
        user.actor.is_cat = is_cat
        changed = True

    if is_bot is not None:
        user.actor.is_bot = is_bot
        user.actor.type = "Service" if is_bot else "Person"
        changed = True

    if locked is not None:
        user.actor.manually_approves_followers = locked
        changed = True

    if discoverable is not None:
        user.actor.discoverable = discoverable
        changed = True

    if avatar:
        from app.services.drive_service import file_to_url, upload_drive_file

        data = await avatar.read()
        try:
            drive_file = await upload_drive_file(
                db=db, owner=user, data=data,
                filename=avatar.filename or "avatar",
                mime_type=avatar.content_type or "image/png",
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        user.actor.avatar_url = file_to_url(drive_file)
        user.actor.avatar_file_id = drive_file.id
        changed = True

    if header:
        from app.services.drive_service import file_to_url, upload_drive_file

        data = await header.read()
        try:
            drive_file = await upload_drive_file(
                db=db, owner=user, data=data,
                filename=header.filename or "header",
                mime_type=header.content_type or "image/png",
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        user.actor.header_url = file_to_url(drive_file)
        user.actor.header_file_id = drive_file.id
        changed = True

    if changed:
        await db.commit()
        await db.refresh(user)

        # Federate profile update to followers
        from app.activitypub.renderer import (
            render_actor,
            render_update_activity,
        )
        from app.services.actor_service import actor_uri
        from app.services.delivery_service import enqueue_delivery
        from app.services.follow_service import get_follower_inboxes

        actor = user.actor
        actor_url = actor_uri(actor)
        actor_data = render_actor(actor)
        update_activity = render_update_activity(
            activity_id=f"{actor_url}#updates/{uuid.uuid4().hex}",
            actor_ap_id=actor_url,
            object_data=actor_data,
        )
        inboxes = await get_follower_inboxes(db, actor.id)
        for inbox_url in inboxes:
            await enqueue_delivery(db, actor.id, inbox_url, update_activity)

    return _user_response(user)


@router.post("/auth/change_password")
async def change_password_endpoint(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await change_password(
            db, user, body.current_password, body.new_password,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True}


# ── TOTP endpoints ──


class TotpEnableRequest(BaseModel):
    code: str


class TotpDisableRequest(BaseModel):
    password: str


class TotpVerifyRequest(BaseModel):
    totp_token: str
    code: str


@router.post("/auth/totp/setup")
async def totp_setup(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.totp_service import (
        encrypt_secret,
        generate_provisioning_uri,
        generate_totp_secret,
    )

    if user.totp_enabled:
        raise HTTPException(
            status_code=400, detail="TOTP is already enabled",
        )

    secret = generate_totp_secret()
    user.totp_secret = encrypt_secret(secret)
    await db.commit()

    uri = generate_provisioning_uri(secret, user.actor.username)
    return {"secret": secret, "provisioning_uri": uri}


@router.post("/auth/totp/enable")
async def totp_enable(
    body: TotpEnableRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.totp_service import (
        decrypt_secret,
        generate_recovery_codes,
        hash_recovery_codes,
        verify_totp_code,
    )

    if user.totp_enabled:
        raise HTTPException(
            status_code=400, detail="TOTP is already enabled",
        )
    if not user.totp_secret:
        raise HTTPException(
            status_code=400, detail="Call /auth/totp/setup first",
        )

    secret = decrypt_secret(user.totp_secret)
    if not verify_totp_code(secret, body.code):
        raise HTTPException(
            status_code=400, detail="Invalid TOTP code",
        )

    recovery_codes = generate_recovery_codes()
    hashed = await asyncio.to_thread(hash_recovery_codes, recovery_codes)

    user.totp_enabled = True
    user.totp_recovery_codes = hashed
    await db.commit()

    return {"recovery_codes": recovery_codes}


@router.post("/auth/totp/disable")
async def totp_disable(
    body: TotpDisableRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import bcrypt as _bcrypt

    if not user.totp_enabled:
        raise HTTPException(
            status_code=400, detail="TOTP is not enabled",
        )

    valid = await asyncio.to_thread(
        _bcrypt.checkpw,
        body.password.encode(),
        user.password_hash.encode(),
    )
    if not valid:
        raise HTTPException(status_code=400, detail="Invalid password")

    user.totp_enabled = False
    user.totp_secret = None
    user.totp_recovery_codes = None
    await db.commit()

    return {"ok": True}


@router.post("/auth/totp/verify")
async def totp_verify(
    body: TotpVerifyRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    from app.valkey_client import valkey

    # Check brute-force lockout before doing anything else
    attempts_key = f"totp_attempts:{body.totp_token}"
    attempts = await valkey.get(attempts_key)
    if attempts is not None and int(attempts) >= TOTP_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail="Too many TOTP attempts. Please wait 5 minutes and try again.",
        )

    user_id_str = await valkey.get(f"totp_pending:{body.totp_token}")
    if not user_id_str:
        raise HTTPException(
            status_code=401, detail="Invalid or expired TOTP token",
        )

    user = await get_user_by_id(db, uuid.UUID(user_id_str))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    from app.services.totp_service import decrypt_secret, verify_totp_code

    secret = decrypt_secret(user.totp_secret)
    code = body.code.strip().replace("-", "")

    if verify_totp_code(secret, code):
        # Valid TOTP code — create session
        pass
    elif user.totp_recovery_codes:
        # Try recovery code
        from app.services.totp_service import verify_recovery_code

        valid, remaining = await asyncio.to_thread(
            verify_recovery_code, body.code.strip(), user.totp_recovery_codes,
        )
        if not valid:
            # Increment attempt counter on failure
            await valkey.incr(attempts_key)
            await valkey.expire(attempts_key, TOTP_LOCKOUT_TTL)
            raise HTTPException(
                status_code=401, detail="Invalid TOTP code",
            )
        user.totp_recovery_codes = remaining
        await db.commit()
    else:
        # Increment attempt counter on failure
        await valkey.incr(attempts_key)
        await valkey.expire(attempts_key, TOTP_LOCKOUT_TTL)
        raise HTTPException(status_code=401, detail="Invalid TOTP code")

    # Successful verification — clean up attempt counter and pending token
    await valkey.delete(attempts_key)
    await valkey.delete(f"totp_pending:{body.totp_token}")

    # Create session
    session_id = uuid.uuid4().hex
    await valkey.set(f"session:{session_id}", str(user.id), ex=86400 * 30)

    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        secure=settings.use_https,
        samesite="lax",
        max_age=86400 * 30,
    )
    return {"ok": True}


@router.get("/auth/totp/status")
async def totp_status(user: User = Depends(get_current_user)):
    return {"totp_enabled": user.totp_enabled}
