"""OAuth 2.0 endpoints (Mastodon compatible)."""

import hashlib
import hmac
import html as html_mod
import json
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
    db: AsyncSession = Depends(get_db),
):
    """Handle login/consent/TOTP/passkey form submission and issue authorization code."""
    # OAuthフォームログインにもレート制限適用 (M-3)
    await _check_oauth_rate_limit(request, "authorize")

    form = await request.form()
    client_id = str(form.get("client_id", ""))
    redirect_uri = str(form.get("redirect_uri", ""))
    scope = str(form.get("scope", "read"))
    response_type = str(form.get("response_type", "code"))
    state = str(form["state"]) if form.get("state") else None
    code_challenge = str(form["code_challenge"]) if form.get("code_challenge") else None
    code_challenge_method = (
        str(form["code_challenge_method"]) if form.get("code_challenge_method") else None
    )
    username = str(form["username"]) if form.get("username") else None
    password = str(form["password"]) if form.get("password") else None
    totp_token = str(form["totp_token"]) if form.get("totp_token") else None
    totp_code = str(form["totp_code"]) if form.get("totp_code") else None
    passkey_credential = str(form["passkey_credential"]) if form.get("passkey_credential") else None
    csrf_token_value = str(form.get("csrf_token", ""))

    # CSRFトークン検証 (M-1)
    is_login_submission = username and password
    is_totp_submission = totp_token and totp_code
    is_passkey_submission = passkey_credential
    if not is_login_submission and not is_passkey_submission:
        if not csrf_token_value or not await _verify_csrf_token(csrf_token_value):
            if not is_totp_submission:
                raise HTTPException(status_code=403, detail="Invalid CSRF token")
    elif csrf_token_value:
        await _verify_csrf_token(csrf_token_value)

    # アプリケーション検証
    if not client_id and totp_token:
        # TOTP送信時はclient_idがフォームにないのでValkeyから復元
        pass
    else:
        result = await db.execute(
            select(OAuthApplication).where(OAuthApplication.client_id == client_id)
        )
        app = result.scalar_one_or_none()
        if not app:
            raise HTTPException(status_code=400, detail="Invalid client_id")

        allowed_uris = [u.strip() for u in app.redirect_uris.split() if u.strip()]
        if redirect_uri not in allowed_uris:
            raise HTTPException(status_code=400, detail="Invalid redirect_uri")

    from app.valkey_client import valkey

    # ── TOTP検証パス ──
    if is_totp_submission:
        data_str = await valkey.get(f"totp_pending_oauth:{totp_token}")
        if not data_str:
            raise HTTPException(status_code=401, detail="TOTP session expired")

        data = json.loads(data_str)
        from app.services.user_service import get_user_by_id

        user = await get_user_by_id(db, uuid.UUID(data["user_id"]))
        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        from app.services.totp_service import decrypt_secret, verify_totp_code

        secret = decrypt_secret(user.totp_secret)
        code = totp_code.strip().replace("-", "")
        totp_valid = verify_totp_code(secret, code)

        if not totp_valid and user.totp_recovery_codes:
            from app.services.totp_service import verify_recovery_code

            valid, remaining = verify_recovery_code(
                totp_code.strip(), user.totp_recovery_codes
            )
            if valid:
                user.totp_recovery_codes = remaining
                await db.commit()
                totp_valid = True

        if not totp_valid:
            csrf_token = await _generate_csrf_token()
            return _render_totp_form(
                totp_token=totp_token,
                app_name=data.get("app_name", ""),
                csrf_token=csrf_token,
                error="Invalid verification code",
            )

        await valkey.delete(f"totp_pending_oauth:{totp_token}")

        # ValkeyからOAuthパラメータを復元
        result = await db.execute(
            select(OAuthApplication).where(
                OAuthApplication.client_id == data["client_id"]
            )
        )
        app = result.scalar_one_or_none()
        if not app:
            raise HTTPException(status_code=400, detail="Invalid client_id")

        return await _issue_authorization_code(
            db=db,
            app=app,
            user_id=user.id,
            redirect_uri=data["redirect_uri"],
            scope=data["scope"],
            state=data.get("state"),
            code_challenge=data.get("code_challenge"),
            code_challenge_method=data.get("code_challenge_method"),
        )

    # ── Passkey認証パス ──
    if is_passkey_submission:
        try:
            cred = json.loads(passkey_credential)
        except (json.JSONDecodeError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid passkey credential")

        challenge_id = cred.pop("challengeId", None)
        if not challenge_id:
            raise HTTPException(status_code=400, detail="Missing challengeId")

        from app.services import passkey_service

        try:
            user = await passkey_service.verify_authentication_response(
                db=db, challenge_id=challenge_id, credential_json=cred,
            )
        except Exception:
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
                error="Passkey authentication failed",
                csrf_token=csrf_token,
            )

        # Passkey (WebAuthn) はデバイス所持+生体認証/PINで既にMFAを満たすため、
        # TOTP追加検証は不要。パスワード認証時のみTOTPを要求する。
        return await _issue_authorization_code(
            db=db, app=app, user_id=user.id, redirect_uri=redirect_uri,
            scope=scope, state=state, code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
        )

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

        # TOTP チェック
        if user.totp_enabled:
            return await _redirect_to_totp(
                valkey, user, app, client_id, redirect_uri, scope,
                response_type, state, code_challenge, code_challenge_method,
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


OAUTH_TOTP_TTL = 300  # 5 minutes


async def _redirect_to_totp(valkey, user, app, client_id, redirect_uri, scope,
                             response_type, state, code_challenge, code_challenge_method):
    """Store OAuth params in Valkey and render TOTP form."""
    totp_token = secrets.token_urlsafe(32)
    await valkey.set(
        f"totp_pending_oauth:{totp_token}",
        json.dumps({
            "user_id": str(user.id),
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "response_type": response_type,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "app_name": app.name,
        }),
        ex=OAUTH_TOTP_TTL,
    )
    csrf_token = await _generate_csrf_token()
    return _render_totp_form(totp_token=totp_token, app_name=app.name, csrf_token=csrf_token)


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
) -> RedirectResponse | HTMLResponse:
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

    if redirect_uri == "urn:ietf:wg:oauth:2.0:oob":
        return _render_oob_page(code=code)

    separator = "&" if "?" in redirect_uri else "?"
    location = f"{redirect_uri}{separator}code={code}"
    if state:
        location += "&" + urlencode({"state": state})

    return RedirectResponse(location, status_code=302)


def _render_oob_page(*, code: str) -> HTMLResponse:
    """Render a page that displays the authorization code for OOB flow."""
    esc = html_mod.escape
    return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Authorization Code</title>
<style>
body {{ font-family: sans-serif; max-width: 400px; margin: 40px auto; padding: 0 16px; }}
.code {{ font-family: monospace; font-size: 18px; padding: 12px;
  background: #f5f5f5; border: 1px solid #ddd; border-radius: 4px;
  word-break: break-all; user-select: all; text-align: center; }}
</style></head><body>
<h2>Authorization successful</h2>
<p>Copy this authorization code and paste it into your application:</p>
<div class="code">{esc(code)}</div>
<p>You can close this window after copying the code.</p>
</body></html>""")


def _render_totp_form(
    *,
    totp_token: str,
    app_name: str,
    csrf_token: str = "",
    error: str | None = None,
) -> HTMLResponse:
    """Render a TOTP verification form for OAuth flow."""
    esc = html_mod.escape
    error_html = f'<p style="color:red">{esc(error)}</p>' if error else ""

    return HTMLResponse(
        f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Two-Factor Authentication</title>
<style>
body {{ font-family: sans-serif; max-width: 400px; margin: 40px auto; padding: 0 16px; }}
h2 {{ margin-bottom: 4px; }}
.app-name {{ color: #666; margin-top: 0; }}
label {{ display: block; margin-top: 12px; font-weight: bold; }}
input[type=text] {{
  width: 100%; padding: 8px; margin-top: 4px; box-sizing: border-box;
  border: 1px solid #ccc; border-radius: 4px; font-size: 18px;
  letter-spacing: 4px; text-align: center;
}}
button {{ margin-top: 16px; padding: 10px 20px; width: 100%;
  background: #6364ff; color: white; border: none; border-radius: 4px;
  font-size: 16px; cursor: pointer; }}
button:hover {{ background: #4f50e6; }}
p.hint {{ color: #888; font-size: 13px; margin-top: 4px; }}
</style></head><body>
<h2>Two-Factor Authentication</h2>
<p class="app-name">{esc(app_name)}</p>
{error_html}
<form method="POST" action="/oauth/authorize">
<input type="hidden" name="totp_token" value="{esc(totp_token)}">
<input type="hidden" name="csrf_token" value="{esc(csrf_token)}">
<input type="hidden" name="client_id" value="">
<input type="hidden" name="redirect_uri" value="">
<label for="totp_code">Verification Code</label>
<input type="text" id="totp_code" name="totp_code" required autofocus
  autocomplete="one-time-code" inputmode="numeric" maxlength="11"
  pattern="[0-9]{{6}}|[a-zA-Z0-9]{{5}}-[a-zA-Z0-9]{{5}}"
  placeholder="000000">
<p class="hint">Enter your 6-digit code or a recovery code.</p>
<button type="submit">Verify</button>
</form></body></html>"""
    )


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
.divider {{ text-align: center; margin: 16px 0 8px; color: #888; font-size: 14px; }}
#passkey-btn {{ background: #333; }}
#passkey-btn:hover {{ background: #111; }}
#passkey-error {{ color: red; font-size: 13px; display: none; margin-top: 8px; }}
</style></head><body>
<h2>Authorize</h2>
<p class="app-name">{esc(app_name)}</p>
{error_html}
<form id="login-form" method="POST" action="/oauth/authorize">
{hidden_inputs}
<input type="hidden" id="passkey_credential" name="passkey_credential" value="">
<label for="username">Username</label>
<input type="text" id="username" name="username" required autofocus>
<label for="password">Password</label>
<input type="password" id="password" name="password" required>
<button type="submit">Log in and Authorize</button>
</form>
<div id="passkey-section" style="display:none">
<div class="divider">or</div>
<button id="passkey-btn" onclick="passkeyLogin()">Sign in with Passkey</button>
<p id="passkey-error"></p>
</div>
<script>
function b64url(buf) {{
  var b = new Uint8Array(buf), s = "";
  for (var i = 0; i < b.length; i++) s += String.fromCharCode(b[i]);
  return btoa(s).replace(/\\+/g, "-").replace(/\\//g, "_").replace(/=/g, "");
}}
function b64dec(s) {{
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  while (s.length % 4) s += "=";
  var bin = atob(s), a = new Uint8Array(bin.length);
  for (var i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i);
  return a.buffer;
}}
async function passkeyLogin() {{
  var errEl = document.getElementById("passkey-error");
  errEl.style.display = "none";
  try {{
    var resp = await fetch("/api/v1/passkey/authenticate/options", {{method:"POST"}});
    if (!resp.ok) throw new Error("Failed to get options");
    var opts = await resp.json();
    var cid = opts.challengeId;
    delete opts.challengeId;
    opts.challenge = b64dec(opts.challenge);
    if (opts.allowCredentials) {{
      opts.allowCredentials = opts.allowCredentials.map(function(c) {{
        return Object.assign({{}}, c, {{id: b64dec(c.id), type: "public-key"}});
      }});
    }}
    var cred = await navigator.credentials.get({{publicKey: opts}});
    if (!cred) throw new Error("Cancelled");
    var r = cred.response;
    var payload = JSON.stringify({{
      challengeId: cid, id: cred.id, rawId: b64url(cred.rawId),
      type: cred.type,
      response: {{
        authenticatorData: b64url(r.authenticatorData),
        clientDataJSON: b64url(r.clientDataJSON),
        signature: b64url(r.signature),
        userHandle: r.userHandle ? b64url(r.userHandle) : null
      }}
    }});
    document.getElementById("passkey_credential").value = payload;
    document.getElementById("username").removeAttribute("required");
    document.getElementById("password").removeAttribute("required");
    document.getElementById("login-form").submit();
  }} catch(e) {{
    errEl.textContent = e.message || "Passkey authentication failed";
    errEl.style.display = "block";
  }}
}}
if (window.PublicKeyCredential) {{
  document.getElementById("passkey-section").style.display = "block";
}}
</script>
</body></html>"""
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
