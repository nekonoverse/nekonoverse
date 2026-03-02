"""OAuth 2.0 endpoints (Mastodon compatible)."""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.oauth import OAuthApplication, OAuthAuthorizationCode, OAuthToken
from app.models.user import User

router = APIRouter(tags=["oauth"])


class AppCreateRequest(BaseModel):
    client_name: str
    redirect_uris: str
    scopes: str = "read"
    website: str | None = None


@router.post("/api/v1/apps")
async def create_app(body: AppCreateRequest, db: AsyncSession = Depends(get_db)):
    """Register an OAuth application."""
    app = OAuthApplication(
        name=body.client_name,
        client_id=secrets.token_urlsafe(32),
        client_secret=secrets.token_urlsafe(64),
        redirect_uris=body.redirect_uris,
        scopes=body.scopes,
        website=body.website,
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)

    return {
        "id": str(app.id),
        "name": app.name,
        "client_id": app.client_id,
        "client_secret": app.client_secret,
        "redirect_uri": app.redirect_uris,
        "website": app.website,
    }


@router.get("/oauth/authorize")
async def authorize_form(
    response_type: str = Query("code"),
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    scope: str = Query("read"),
    state: str | None = Query(None),
    code_challenge: str | None = Query(None),
    code_challenge_method: str | None = Query(None),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """Show authorization form (simplified -- auto-authorize if logged in)."""
    # Validate application
    result = await db.execute(
        select(OAuthApplication).where(OAuthApplication.client_id == client_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=400, detail="Invalid client_id")

    if redirect_uri not in app.redirect_uris.split():
        raise HTTPException(status_code=400, detail="Invalid redirect_uri")

    # Check if user is logged in
    session_id = request.cookies.get("nekonoverse_session")
    if not session_id:
        # Return a simple login form
        return HTMLResponse(f"""
        <html><body style="font-family:sans-serif;max-width:400px;margin:40px auto">
        <h2>Authorize {app.name}</h2>
        <p>Please <a href="/login?redirect=/oauth/authorize?client_id={client_id}&redirect_uri={redirect_uri}&scope={scope}&response_type={response_type}">log in</a> first.</p>
        </body></html>
        """)

    from app.valkey_client import valkey_pool

    async with valkey_pool.client() as conn:
        user_id_str = await conn.get(f"session:{session_id}")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Session expired")

    # Generate authorization code
    code = secrets.token_urlsafe(32)
    auth_code = OAuthAuthorizationCode(
        code=code,
        application_id=app.id,
        user_id=uuid.UUID(user_id_str),
        redirect_uri=redirect_uri,
        scopes=scope,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db.add(auth_code)
    await db.commit()

    # Redirect with code
    separator = "&" if "?" in redirect_uri else "?"
    location = f"{redirect_uri}{separator}code={code}"
    if state:
        location += f"&state={state}"

    return RedirectResponse(location, status_code=302)


@router.post("/oauth/token")
async def token(
    grant_type: str = Form(...),
    code: str | None = Form(None),
    client_id: str = Form(...),
    client_secret: str = Form(...),
    redirect_uri: str | None = Form(None),
    code_verifier: str | None = Form(None),
    scope: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Exchange authorization code for access token."""
    # Validate application
    result = await db.execute(
        select(OAuthApplication).where(
            OAuthApplication.client_id == client_id,
            OAuthApplication.client_secret == client_secret,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=401, detail="Invalid client credentials")

    if grant_type == "authorization_code":
        if not code:
            raise HTTPException(status_code=400, detail="Missing code")

        result = await db.execute(
            select(OAuthAuthorizationCode).where(
                OAuthAuthorizationCode.code == code,
                OAuthAuthorizationCode.application_id == app.id,
            )
        )
        auth_code = result.scalar_one_or_none()
        if not auth_code:
            raise HTTPException(status_code=400, detail="Invalid code")

        if auth_code.expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="Code expired")

        if redirect_uri and auth_code.redirect_uri != redirect_uri:
            raise HTTPException(status_code=400, detail="Redirect URI mismatch")

        # PKCE verification
        if auth_code.code_challenge and auth_code.code_challenge_method == "S256":
            if not code_verifier:
                raise HTTPException(status_code=400, detail="Missing code_verifier")
            challenge = (
                hashlib.sha256(code_verifier.encode())
                .digest()
            )
            import base64

            expected = base64.urlsafe_b64encode(challenge).rstrip(b"=").decode()
            if expected != auth_code.code_challenge:
                raise HTTPException(status_code=400, detail="Invalid code_verifier")

        # Create access token
        access_token = secrets.token_urlsafe(64)
        token_obj = OAuthToken(
            access_token=access_token,
            scopes=auth_code.scopes,
            application_id=app.id,
            user_id=auth_code.user_id,
        )
        db.add(token_obj)

        # Delete used code
        await db.delete(auth_code)
        await db.commit()

        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "scope": auth_code.scopes,
            "created_at": int(token_obj.created_at.timestamp()),
        }

    elif grant_type == "client_credentials":
        access_token = secrets.token_urlsafe(64)
        token_obj = OAuthToken(
            access_token=access_token,
            scopes=scope or "read",
            application_id=app.id,
            user_id=None,
        )
        db.add(token_obj)
        await db.commit()

        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "scope": scope or "read",
            "created_at": int(token_obj.created_at.timestamp()),
        }

    else:
        raise HTTPException(status_code=400, detail="Unsupported grant_type")


@router.post("/oauth/revoke")
async def revoke_token(
    token: str = Form(...),
    client_id: str = Form(...),
    client_secret: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Revoke an access token."""
    result = await db.execute(
        select(OAuthToken).where(OAuthToken.access_token == token)
    )
    token_obj = result.scalar_one_or_none()
    if token_obj:
        token_obj.revoked_at = datetime.now(timezone.utc)
        await db.commit()

    return {}
