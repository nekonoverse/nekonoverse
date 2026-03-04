import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn.helpers import bytes_to_base64url

from app.api.auth import SESSION_COOKIE, get_session_id
from app.dependencies import get_current_user, get_db
from app.services import passkey_service

router = APIRouter(prefix="/api/v1/passkey", tags=["passkey"])


# ── Schemas ────────────────────────────────────────────────────────────────


class PasskeyRegisterVerifyRequest(BaseModel):
    id: str
    rawId: str
    type: str
    response: dict
    authenticatorAttachment: str | None = None
    clientExtensionResults: dict = {}
    name: str | None = None


class PasskeyAuthOptionsResponse(BaseModel):
    challengeId: str


class PasskeyAuthVerifyRequest(BaseModel):
    challengeId: str
    id: str
    rawId: str
    type: str
    response: dict
    authenticatorAttachment: str | None = None
    clientExtensionResults: dict = {}


class PasskeyCredentialResponse(BaseModel):
    id: str
    credential_id: str
    name: str | None
    aaguid: str | None
    sign_count: int
    created_at: str
    last_used_at: str | None


# ── Registration flow ──────────────────────────────────────────────────────


@router.post("/register/options")
async def register_options(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    session_id = get_session_id(request)
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    options = await passkey_service.generate_registration_options(user, session_id)
    return options


@router.post("/register/verify", response_model=PasskeyCredentialResponse)
async def register_verify(
    body: PasskeyRegisterVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    session_id = get_session_id(request)
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    credential_json = body.model_dump(exclude={"name"})

    try:
        passkey = await passkey_service.verify_registration_response(
            db=db,
            session_id=session_id,
            credential_json=credential_json,
            name=body.name,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return PasskeyCredentialResponse(
        id=str(passkey.id),
        credential_id=bytes_to_base64url(passkey.credential_id),
        name=passkey.name,
        aaguid=passkey.aaguid,
        sign_count=passkey.sign_count,
        created_at=passkey.created_at.isoformat(),
        last_used_at=passkey.last_used_at.isoformat() if passkey.last_used_at else None,
    )


# ── Authentication flow ────────────────────────────────────────────────────


@router.post("/authenticate/options")
async def authenticate_options():
    challenge_id = secrets.token_hex(16)
    options = await passkey_service.generate_authentication_options(challenge_id)
    return JSONResponse(content={"challengeId": challenge_id, **options})


@router.post("/authenticate/verify")
async def authenticate_verify(
    body: PasskeyAuthVerifyRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    credential_json = body.model_dump(exclude={"challengeId"})

    try:
        user = await passkey_service.verify_authentication_response(
            db=db,
            challenge_id=body.challengeId,
            credential_json=credential_json,
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

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


# ── Credential management ──────────────────────────────────────────────────


@router.get("/credentials", response_model=list[PasskeyCredentialResponse])
async def list_credentials(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    passkeys = await passkey_service.list_passkeys(db, user)
    return [
        PasskeyCredentialResponse(
            id=str(p.id),
            credential_id=bytes_to_base64url(p.credential_id),
            name=p.name,
            aaguid=p.aaguid,
            sign_count=p.sign_count,
            created_at=p.created_at.isoformat(),
            last_used_at=p.last_used_at.isoformat() if p.last_used_at else None,
        )
        for p in passkeys
    ]


@router.delete("/credentials/{passkey_id}", status_code=204)
async def delete_credential(
    passkey_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        await passkey_service.delete_passkey(db, user, passkey_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
