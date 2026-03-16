"""OAuth 2.0 endpoints (Mastodon compatible)."""

import hashlib
import hmac
import html as html_mod
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.oauth import OAuthApplication, OAuthAuthorizationCode, OAuthToken

router = APIRouter(tags=["oauth"])

# トークン有効期限: 90日
TOKEN_LIFETIME = timedelta(days=90)

# OAuthレート制限
OAUTH_MAX_ATTEMPTS = 20
OAUTH_LOCKOUT_TTL = 300  # 5 minutes


def _hash_token(token: str) -> str:
    """Hash an OAuth token for secure storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def _verify_client_secret(stored: str, provided: str) -> bool:
    """Verify client_secret: supports both hashed (SHA-256) and legacy plain format."""
    hashed = _hash_token(provided)
    if hmac.compare_digest(stored, hashed):
        return True
    # レガシー互換: 平文で保存されたclient_secretとの比較
    return hmac.compare_digest(stored, provided)


async def _check_oauth_rate_limit(request: Request, endpoint: str) -> None:
    """Check rate limit for OAuth endpoints."""
    from app.valkey_client import valkey

    client_ip = request.client.host if request.client else "unknown"
    key = f"oauth_attempts:{endpoint}:{client_ip}"
    try:
        attempts = await valkey.get(key)
        if attempts is not None and int(attempts) >= OAUTH_MAX_ATTEMPTS:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please wait and try again.",
            )
        await valkey.incr(key)
        await valkey.expire(key, OAUTH_LOCKOUT_TTL)
    except HTTPException:
        raise
    except Exception:
        pass  # レート制限の失敗でリクエストをブロックしない


class AppCreateRequest(BaseModel):
    client_name: str
    redirect_uris: str
    scopes: str = "read"
    website: str | None = None


async def _parse_app_create(request: Request) -> AppCreateRequest:
    """Parse POST /api/v1/apps from JSON or form-urlencoded."""
    data = await _parse_form_or_json(request)
    return AppCreateRequest(**data)


async def _parse_form_or_json(request: Request) -> dict:
    """Parse request body from JSON or form-urlencoded."""
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        return await request.json()
    form = await request.form()
    return dict(form)


@router.post("/api/v1/apps")
async def create_app(
    request: Request, db: AsyncSession = Depends(get_db),
):
    """Register an OAuth application."""
    await _check_oauth_rate_limit(request, "apps")
    body = await _parse_app_create(request)
    # M-2: client_secretをハッシュ化して保存、プレーンテキストはレスポンスのみ
    raw_secret = secrets.token_urlsafe(64)
    app = OAuthApplication(
        name=body.client_name,
        client_id=secrets.token_urlsafe(32),
        client_secret=_hash_token(raw_secret),
        redirect_uris=body.redirect_uris,
        scopes=body.scopes,
        website=body.website,
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)

    # VAPID公開鍵 (Web Push用)
    vapid_key = ""
    try:
        from app.services.push_service import get_vapid_public_key_base64url, is_push_enabled

        if await is_push_enabled(db):
            vapid_key = get_vapid_public_key_base64url() or ""
    except Exception:
        pass

    return {
        "id": str(app.id),
        "name": app.name,
        "website": app.website,
        "scopes": app.scopes.split(),
        "redirect_uris": [u.strip() for u in app.redirect_uris.split() if u.strip()],
        "redirect_uri": app.redirect_uris,
        "client_id": app.client_id,
        "client_secret": raw_secret,
        "client_secret_expires_at": 0,
        "vapid_key": vapid_key,
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

    # リダイレクトURIの厳密な完全一致検証
    allowed_uris = [u.strip() for u in app.redirect_uris.split() if u.strip()]
    if redirect_uri not in allowed_uris:
        raise HTTPException(status_code=400, detail="Invalid redirect_uri")

    # 危険なスキームのブロック (カスタムスキームはMastodonクライアントアプリで使用)
    parsed_redirect = urlparse(redirect_uri)
    _blocked_schemes = {"javascript", "data", "vbscript", "blob"}
    if parsed_redirect.scheme in _blocked_schemes:
        raise HTTPException(status_code=400, detail="Invalid redirect_uri scheme")

    # セッションからユーザーを取得
    user_id = await _get_session_user_id(request)

    if not user_id:
        # 未ログイン: ログインフォームを表示
        csrf_token = await _generate_csrf_token()
        return _render_login_form(
            app_name=app.name,
            client_id=client_id,
            redirect_uri=redirect_uri,
            scope=scope,
            response_type=response_type,
            state=state,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            csrf_token=csrf_token,
        )

    # H-1: ログイン済みでも必ず同意画面を表示する (自動認可を廃止)
    csrf_token = await _generate_csrf_token()
    return _render_consent_form(
        app_name=app.name,
        client_id=client_id,
        redirect_uri=redirect_uri,
        scope=scope,
        response_type=response_type,
        state=state,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        csrf_token=csrf_token,
    )


@router.post("/oauth/authorize")
async def authorize_submit(
    request: Request,
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    scope: str = Form("read"),
    response_type: str = Form("code"),
    state: str | None = Form(None),
    code_challenge: str | None = Form(None),
    code_challenge_method: str | None = Form(None),
    username: str | None = Form(None),
    password: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Handle login/consent form submission and issue authorization code."""
    # OAuthフォームログインにもレート制限適用 (M-3)
    await _check_oauth_rate_limit(request, "authorize")

    # CSRFトークン検証 (M-1): 同意フォーム(ログイン済み)では必須、
    # ログインフォーム(username/password送信)ではクレデンシャル自体が認証
    csrf_token_value = (await request.form()).get("csrf_token", "")
    is_login_submission = username and password
    if not is_login_submission:
        if not csrf_token_value or not await _verify_csrf_token(str(csrf_token_value)):
            raise HTTPException(status_code=403, detail="Invalid CSRF token")
    elif csrf_token_value:
        # ログインフォームでもCSRFトークンがあれば検証する
        await _verify_csrf_token(str(csrf_token_value))

    # アプリケーション検証
    result = await db.execute(
        select(OAuthApplication).where(OAuthApplication.client_id == client_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=400, detail="Invalid client_id")

    allowed_uris = [u.strip() for u in app.redirect_uris.split() if u.strip()]
    if redirect_uri not in allowed_uris:
        raise HTTPException(status_code=400, detail="Invalid redirect_uri")

    # セッションからユーザーを取得(既にログイン済みの場合)
    user_id = await _get_session_user_id(request)

    # セッションがなければフォームからログイン
    if not user_id:
        csrf_token = await _generate_csrf_token()
        if not username or not password:
            return _render_login_form(
                app_name=app.name,
                client_id=client_id,
                redirect_uri=redirect_uri,
                scope=scope,
                response_type=response_type,
                state=state,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
                error="Username and password are required",
                csrf_token=csrf_token,
            )

        from app.services.user_service import authenticate_user

        user = await authenticate_user(db, username, password)
        if not user:
            return _render_login_form(
                app_name=app.name,
                client_id=client_id,
                redirect_uri=redirect_uri,
                scope=scope,
                response_type=response_type,
                state=state,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
                error="Invalid username or password",
                csrf_token=csrf_token,
            )

        await db.refresh(user, ["actor"])
        if user.actor and user.actor.is_suspended:
            raise HTTPException(status_code=403, detail="Account is suspended")
        if user.approval_status == "pending":
            raise HTTPException(
                status_code=403, detail="Your registration is pending approval"
            )

        user_id = user.id

    return await _issue_authorization_code(
        db=db,
        app=app,
        user_id=user_id,
        redirect_uri=redirect_uri,
        scope=scope,
        state=state,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
    )


async def _get_session_user_id(request: Request) -> uuid.UUID | None:
    """Extract user ID from session cookie. Returns None if not logged in."""
    session_id = request.cookies.get("nekonoverse_session")
    if not session_id:
        return None

    from app.valkey_client import valkey

    user_id_str = await valkey.get(f"session:{session_id}")
    if not user_id_str:
        return None
    return uuid.UUID(user_id_str)


async def _generate_csrf_token() -> str:
    """Generate a CSRF token and store it in Valkey."""
    from app.valkey_client import valkey

    token = secrets.token_urlsafe(32)
    await valkey.set(f"csrf:{token}", "1", ex=600)  # 10分間有効
    return token


async def _verify_csrf_token(token: str) -> bool:
    """Verify and consume a CSRF token."""
    from app.valkey_client import valkey

    result = await valkey.get(f"csrf:{token}")
    if result:
        await valkey.delete(f"csrf:{token}")
        return True
    return False


async def _issue_authorization_code(
    *,
    db: AsyncSession,
    app: OAuthApplication,
    user_id: uuid.UUID,
    redirect_uri: str,
    scope: str,
    state: str | None,
    code_challenge: str | None,
    code_challenge_method: str | None,
) -> RedirectResponse:
    """Generate an authorization code and redirect to the client."""
    from app.services.user_service import get_user_by_id

    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if user.actor and user.actor.is_suspended:
        raise HTTPException(status_code=403, detail="Account is suspended")
    if user.approval_status == "pending":
        raise HTTPException(status_code=403, detail="Your registration is pending approval")

    code = secrets.token_urlsafe(32)
    auth_code = OAuthAuthorizationCode(
        code=code,
        application_id=app.id,
        user_id=user_id,
        redirect_uri=redirect_uri,
        scopes=scope,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db.add(auth_code)
    await db.commit()

    separator = "&" if "?" in redirect_uri else "?"
    location = f"{redirect_uri}{separator}code={code}"
    if state:
        location += "&" + urlencode({"state": state})

    return RedirectResponse(location, status_code=302)


def _render_login_form(
    *,
    app_name: str,
    client_id: str,
    redirect_uri: str,
    scope: str,
    response_type: str,
    state: str | None,
    code_challenge: str | None,
    code_challenge_method: str | None,
    error: str | None = None,
    csrf_token: str = "",
) -> HTMLResponse:
    """Render a self-contained login form that POSTs to /oauth/authorize."""
    esc = html_mod.escape
    error_html = f'<p style="color:red">{esc(error)}</p>' if error else ""

    hidden_fields = [
        ("client_id", client_id),
        ("redirect_uri", redirect_uri),
        ("scope", scope),
        ("response_type", response_type),
        ("csrf_token", csrf_token),
    ]
    if state:
        hidden_fields.append(("state", state))
    if code_challenge:
        hidden_fields.append(("code_challenge", code_challenge))
    if code_challenge_method:
        hidden_fields.append(("code_challenge_method", code_challenge_method))

    hidden_inputs = "\n".join(
        f'<input type="hidden" name="{esc(k)}" value="{esc(v)}">'
        for k, v in hidden_fields
    )

    return HTMLResponse(
        f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Authorize {esc(app_name)}</title>
<style>
body {{ font-family: sans-serif; max-width: 400px; margin: 40px auto; padding: 0 16px; }}
h2 {{ margin-bottom: 4px; }}
.app-name {{ color: #666; margin-top: 0; }}
label {{ display: block; margin-top: 12px; font-weight: bold; }}
input[type=text], input[type=password] {{
  width: 100%; padding: 8px; margin-top: 4px; box-sizing: border-box;
  border: 1px solid #ccc; border-radius: 4px;
}}
button {{ margin-top: 16px; padding: 10px 20px; width: 100%;
  background: #6364ff; color: white; border: none; border-radius: 4px;
  font-size: 16px; cursor: pointer; }}
button:hover {{ background: #4f50e6; }}
</style></head><body>
<h2>Authorize</h2>
<p class="app-name">{esc(app_name)}</p>
{error_html}
<form method="POST" action="/oauth/authorize">
{hidden_inputs}
<label for="username">Username</label>
<input type="text" id="username" name="username" required autofocus>
<label for="password">Password</label>
<input type="password" id="password" name="password" required>
<button type="submit">Log in and Authorize</button>
</form></body></html>"""
    )


def _render_consent_form(
    *,
    app_name: str,
    client_id: str,
    redirect_uri: str,
    scope: str,
    response_type: str,
    state: str | None,
    code_challenge: str | None,
    code_challenge_method: str | None,
    csrf_token: str = "",
) -> HTMLResponse:
    """Render a consent form for logged-in users to authorize an app."""
    esc = html_mod.escape

    hidden_fields = [
        ("client_id", client_id),
        ("redirect_uri", redirect_uri),
        ("scope", scope),
        ("response_type", response_type),
        ("csrf_token", csrf_token),
    ]
    if state:
        hidden_fields.append(("state", state))
    if code_challenge:
        hidden_fields.append(("code_challenge", code_challenge))
    if code_challenge_method:
        hidden_fields.append(("code_challenge_method", code_challenge_method))

    hidden_inputs = "\n".join(
        f'<input type="hidden" name="{esc(k)}" value="{esc(v)}">'
        for k, v in hidden_fields
    )

    scope_list = scope.split()
    scope_items = "\n".join(f"<li>{esc(s)}</li>" for s in scope_list)

    return HTMLResponse(
        f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Authorize {esc(app_name)}</title>
<style>
body {{ font-family: sans-serif; max-width: 400px; margin: 40px auto; padding: 0 16px; }}
h2 {{ margin-bottom: 4px; }}
.app-name {{ color: #666; margin-top: 0; font-size: 1.1em; }}
ul {{ padding-left: 20px; }}
button {{ margin-top: 16px; padding: 10px 20px; width: 100%;
  background: #6364ff; color: white; border: none; border-radius: 4px;
  font-size: 16px; cursor: pointer; }}
button:hover {{ background: #4f50e6; }}
.deny {{ background: #888; margin-top: 8px; }}
.deny:hover {{ background: #666; }}
</style></head><body>
<h2>Authorize application</h2>
<p class="app-name">{esc(app_name)}</p>
<p>This application requests the following permissions:</p>
<ul>{scope_items}</ul>
<form method="POST" action="/oauth/authorize">
{hidden_inputs}
<button type="submit">Authorize</button>
</form>
</body></html>"""
    )


@router.post("/oauth/token")
async def token(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Exchange authorization code for access token."""
    await _check_oauth_rate_limit(request, "token")
    body = await _parse_form_or_json(request)
    grant_type = body.get("grant_type")
    code = body.get("code")
    client_id = body.get("client_id")
    client_secret = body.get("client_secret")
    redirect_uri = body.get("redirect_uri")
    code_verifier = body.get("code_verifier")
    scope = body.get("scope")

    if not grant_type or not client_id or not client_secret:
        raise HTTPException(status_code=400, detail="Missing required parameters")

    # Validate application
    result = await db.execute(
        select(OAuthApplication).where(OAuthApplication.client_id == client_id)
    )
    app = result.scalar_one_or_none()
    if not app or not _verify_client_secret(app.client_secret, client_secret):
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

        # L-3: redirect_uriは必須 (RFC 6749 Section 4.1.3)
        if not redirect_uri:
            raise HTTPException(status_code=400, detail="redirect_uri is required")
        if auth_code.redirect_uri != redirect_uri:
            raise HTTPException(status_code=400, detail="Redirect URI mismatch")

        # PKCE verification (S256のみサポート、plainメソッドは拒否)
        if auth_code.code_challenge:
            if auth_code.code_challenge_method != "S256":
                raise HTTPException(
                    status_code=400, detail="Unsupported code_challenge_method (use S256)"
                )
            if not code_verifier:
                raise HTTPException(status_code=400, detail="Missing code_verifier")
            challenge = hashlib.sha256(code_verifier.encode()).digest()
            import base64

            expected = base64.urlsafe_b64encode(challenge).rstrip(b"=").decode()
            if expected != auth_code.code_challenge:
                raise HTTPException(status_code=400, detail="Invalid code_verifier")

        # Create access token (ハッシュ化して保存、プレーンテキストはレスポンスのみ)
        access_token = secrets.token_urlsafe(64)
        token_obj = OAuthToken(
            access_token=_hash_token(access_token),
            scopes=auth_code.scopes,
            application_id=app.id,
            user_id=auth_code.user_id,
            expires_at=datetime.now(timezone.utc) + TOKEN_LIFETIME,
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
            access_token=_hash_token(access_token),
            scopes=scope or "read",
            application_id=app.id,
            user_id=None,
            expires_at=datetime.now(timezone.utc) + TOKEN_LIFETIME,
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
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Revoke an access token."""
    await _check_oauth_rate_limit(request, "revoke")
    body = await _parse_form_or_json(request)
    token = body.get("token")
    client_id = body.get("client_id")
    client_secret = body.get("client_secret")

    if not token or not client_id or not client_secret:
        raise HTTPException(status_code=400, detail="Missing required parameters")

    # クライアント認証
    result = await db.execute(
        select(OAuthApplication).where(OAuthApplication.client_id == client_id)
    )
    app = result.scalar_one_or_none()
    if not app or not _verify_client_secret(app.client_secret, client_secret):
        raise HTTPException(status_code=401, detail="Invalid client credentials")

    # ハッシュ化トークンで検索(新方式)、見つからなければプレーンテキスト(互換)
    token_hash = _hash_token(token)
    result = await db.execute(select(OAuthToken).where(OAuthToken.access_token == token_hash))
    token_obj = result.scalar_one_or_none()
    if not token_obj:
        result = await db.execute(select(OAuthToken).where(OAuthToken.access_token == token))
        token_obj = result.scalar_one_or_none()
    if token_obj:
        # トークンが要求元のアプリケーションに属するか検証
        if token_obj.application_id != app.id:
            raise HTTPException(status_code=403, detail="Token does not belong to this client")
        token_obj.revoked_at = datetime.now(timezone.utc)
        await db.commit()

    return {}
