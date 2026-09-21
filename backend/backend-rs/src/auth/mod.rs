//! `app/dependencies.py` の `get_current_user`/`get_oauth_user`/`require_oauth_scope` を
//! 移植した axum extractor。以降の全 Stage (書き込みを伴うエンドポイント) で
//! 再利用する認証基盤。
//!
//! Bearer トークン (OAuth) → `oauth_tokens` 照合、なければセッション Cookie →
//! Valkey `session:{id}` 照合、の2経路。それぞれ Python 側の副作用
//! (無効化されたセッションの Valkey 削除、`X-Deletion-Pending` ヘッダー付与) も
//! 忠実に再現する。

use axum::extract::FromRequestParts;
use axum::http::request::Parts;
use axum::http::{header, HeaderValue, Method, StatusCode};
use chrono::{DateTime, Utc};
use redis::AsyncCommands;
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::error::AppError;
use crate::hmac_sig::to_hex;
use crate::state::AppState;

#[derive(Debug, Clone)]
pub struct CurrentUser {
    pub id: Uuid,
    pub actor_id: Uuid,
    /// Bearer トークン認証時のスコープ一覧。セッション認証時は `None`
    /// (`app.dependencies.require_oauth_scope` のセッション時の「全スコープ許可」と同じ)。
    pub oauth_scopes: Option<Vec<String>>,
}

impl CurrentUser {
    /// `app.dependencies.require_oauth_scope` を移植したもの。
    /// ルートハンドラの先頭で `current_user.require_scope("write:bookmarks")?` のように呼ぶ。
    pub fn require_scope(&self, scope: &str) -> Result<(), AppError> {
        let Some(scopes) = &self.oauth_scopes else {
            return Ok(());
        };
        if scopes.iter().any(|s| s == scope) {
            return Ok(());
        }
        if let Some(prefix) = scope.split_once(':').map(|(p, _)| p) {
            if scopes.iter().any(|s| s == prefix) {
                return Ok(());
            }
        }
        Err(AppError::new(
            StatusCode::FORBIDDEN,
            format!("Insufficient scope: {scope} required"),
        ))
    }
}

#[async_trait::async_trait]
impl FromRequestParts<AppState> for CurrentUser {
    type Rejection = AppError;

    async fn from_request_parts(
        parts: &mut Parts,
        state: &AppState,
    ) -> Result<Self, Self::Rejection> {
        let auth_header = parts
            .headers
            .get(header::AUTHORIZATION)
            .and_then(|v| v.to_str().ok());

        if let Some(token) = auth_header.and_then(|h| h.strip_prefix("Bearer ")) {
            return authenticate_bearer(state, token, &parts.method).await;
        }

        let session_id = parts
            .headers
            .get(header::COOKIE)
            .and_then(|v| v.to_str().ok())
            .and_then(|c| parse_cookie(c, "nekonoverse_session"));

        let Some(session_id) = session_id else {
            return Err(AppError::new(StatusCode::UNAUTHORIZED, "Not authenticated"));
        };

        authenticate_session(state, &session_id).await
    }
}

/// `app.dependencies.get_optional_user` を移植したもの。未認証時は `None`。
/// Bearer 経路は `authenticate_bearer` を再利用しエラーを全て `None` に潰す
/// (Python版の `except HTTPException: return None` と同じ)。セッション経路は
/// 専用の `authenticate_session_optional` を使う — `get_current_user` にしか
/// 無い「削除猶予中は特別扱いしてセッションを残す」分岐が `get_optional_user`
/// には存在せず、停止済みアクターは猶予中かどうかに関わらず一律でセッション
/// 削除・`None` を返すため、`authenticate_session` をそのまま流用すると
/// この一点で挙動が変わってしまう。
pub struct OptionalUser(pub Option<CurrentUser>);

#[async_trait::async_trait]
impl FromRequestParts<AppState> for OptionalUser {
    type Rejection = std::convert::Infallible;

    async fn from_request_parts(
        parts: &mut Parts,
        state: &AppState,
    ) -> Result<Self, Self::Rejection> {
        let auth_header = parts
            .headers
            .get(header::AUTHORIZATION)
            .and_then(|v| v.to_str().ok());

        if let Some(token) = auth_header.and_then(|h| h.strip_prefix("Bearer ")) {
            let user = authenticate_bearer(state, token, &parts.method).await.ok();
            return Ok(OptionalUser(user));
        }

        let session_id = parts
            .headers
            .get(header::COOKIE)
            .and_then(|v| v.to_str().ok())
            .and_then(|c| parse_cookie(c, "nekonoverse_session"));

        let Some(session_id) = session_id else {
            return Ok(OptionalUser(None));
        };

        Ok(OptionalUser(
            authenticate_session_optional(state, &session_id).await,
        ))
    }
}

/// `get_optional_user` のセッション Cookie 経路を移植したもの。
async fn authenticate_session_optional(state: &AppState, session_id: &str) -> Option<CurrentUser> {
    let mut redis = state.redis.clone();
    let key = format!("session:{session_id}");
    let user_id_str: Option<String> = redis.get(&key).await.ok().flatten();
    let user_id = Uuid::parse_str(&user_id_str?).ok()?;

    let row = fetch_user_actor(state, user_id).await.ok().flatten()?;

    if row.is_system
        || row.deleted_at.is_some()
        || row.suspended_at.is_some()
        || row.approval_status == "pending"
    {
        let _: Result<(), _> = redis.del(&key).await;
        return None;
    }

    Some(CurrentUser {
        id: row.id,
        actor_id: row.actor_id,
        oauth_scopes: None,
    })
}

fn parse_cookie(header_value: &str, name: &str) -> Option<String> {
    header_value.split(';').find_map(|kv| {
        let (k, v) = kv.trim().split_once('=')?;
        (k == name).then(|| v.to_string())
    })
}

#[derive(sqlx::FromRow)]
struct OAuthTokenRow {
    scopes: String,
    user_id: Option<Uuid>,
    revoked_at: Option<DateTime<Utc>>,
    expires_at: Option<DateTime<Utc>>,
}

#[derive(sqlx::FromRow)]
struct UserActorRow {
    id: Uuid,
    actor_id: Uuid,
    is_system: bool,
    approval_status: String,
    suspended_at: Option<DateTime<Utc>>,
    deleted_at: Option<DateTime<Utc>>,
    deletion_scheduled_at: Option<DateTime<Utc>>,
}

async fn fetch_user_actor(
    state: &AppState,
    user_id: Uuid,
) -> Result<Option<UserActorRow>, AppError> {
    let row = sqlx::query_as::<_, UserActorRow>(
        r#"
        SELECT u.id, u.actor_id, u.is_system, u.approval_status,
               a.suspended_at, a.deleted_at, a.deletion_scheduled_at
        FROM users u
        JOIN actors a ON a.id = u.actor_id
        WHERE u.id = $1
        "#,
    )
    .bind(user_id)
    .fetch_optional(&state.db)
    .await?;
    Ok(row)
}

/// `app.dependencies.get_oauth_user` + `get_current_user` の H-3 スコープ検証を移植したもの。
async fn authenticate_bearer(
    state: &AppState,
    token: &str,
    method: &Method,
) -> Result<CurrentUser, AppError> {
    let token_hash = to_hex(&Sha256::digest(token.as_bytes()));

    // ハッシュ化トークンで検索(新方式)、見つからなければプレーンテキストで検索(互換)。
    let token_row: Option<OAuthTokenRow> = sqlx::query_as(
        "SELECT scopes, user_id, revoked_at, expires_at FROM oauth_tokens WHERE access_token = $1",
    )
    .bind(&token_hash)
    .fetch_optional(&state.db)
    .await?;

    let token_row = match token_row {
        Some(row) => row,
        None => sqlx::query_as::<_, OAuthTokenRow>(
            "SELECT scopes, user_id, revoked_at, expires_at FROM oauth_tokens WHERE access_token = $1",
        )
        .bind(token)
        .fetch_optional(&state.db)
        .await?
        .ok_or_else(|| AppError::new(StatusCode::UNAUTHORIZED, "Invalid token"))?,
    };

    if token_row.revoked_at.is_some() {
        return Err(AppError::new(StatusCode::UNAUTHORIZED, "Token revoked"));
    }
    if let Some(expires_at) = token_row.expires_at {
        if Utc::now() > expires_at {
            return Err(AppError::new(StatusCode::UNAUTHORIZED, "Token expired"));
        }
    }
    let Some(user_id) = token_row.user_id else {
        return Err(AppError::new(
            StatusCode::UNAUTHORIZED,
            "Token has no associated user",
        ));
    };

    let scopes: Vec<String> = if token_row.scopes.trim().is_empty() {
        vec!["read".to_string()]
    } else {
        token_row
            .scopes
            .split_whitespace()
            .map(str::to_string)
            .collect()
    };

    // H-3: HTTPメソッドに基づくOAuthスコープ検証。
    let is_write_method = matches!(method.as_str(), "POST" | "PUT" | "PATCH" | "DELETE");
    let has_required_scope = if is_write_method {
        scopes
            .iter()
            .any(|s| s == "write" || s.starts_with("write:"))
    } else {
        scopes.iter().any(|s| s == "read" || s.starts_with("read:"))
    };
    if !has_required_scope {
        let kind = if is_write_method { "write" } else { "read" };
        return Err(AppError::new(
            StatusCode::FORBIDDEN,
            format!("Insufficient scope: {kind} access required"),
        ));
    }

    let row = fetch_user_actor(state, user_id)
        .await?
        .ok_or_else(|| AppError::new(StatusCode::UNAUTHORIZED, "User not found"))?;

    if row.is_system {
        return Err(AppError::new(
            StatusCode::FORBIDDEN,
            "System accounts cannot authenticate",
        ));
    }
    if row.deleted_at.is_some() {
        return Err(AppError::new(StatusCode::FORBIDDEN, "Account is deleted"));
    }
    if row.suspended_at.is_some() {
        return Err(AppError::new(StatusCode::FORBIDDEN, "Account is suspended"));
    }
    if row.approval_status == "pending" {
        return Err(AppError::new(
            StatusCode::FORBIDDEN,
            "Your registration is pending approval",
        ));
    }

    Ok(CurrentUser {
        id: row.id,
        actor_id: row.actor_id,
        oauth_scopes: Some(scopes),
    })
}

/// `app.dependencies.get_current_user` のセッション Cookie 経路を移植したもの。
async fn authenticate_session(state: &AppState, session_id: &str) -> Result<CurrentUser, AppError> {
    let mut redis = state.redis.clone();
    let key = format!("session:{session_id}");
    let user_id_str: Option<String> = redis.get(&key).await?;
    let Some(user_id_str) = user_id_str else {
        return Err(AppError::new(StatusCode::UNAUTHORIZED, "Session expired"));
    };
    let user_id = Uuid::parse_str(&user_id_str)
        .map_err(|_| AppError::new(StatusCode::UNAUTHORIZED, "Session expired"))?;

    let row = fetch_user_actor(state, user_id)
        .await?
        .ok_or_else(|| AppError::new(StatusCode::UNAUTHORIZED, "User not found"))?;

    if row.is_system {
        let _: Result<(), _> = redis.del(&key).await;
        return Err(AppError::new(
            StatusCode::FORBIDDEN,
            "System accounts cannot authenticate",
        ));
    }
    if row.deleted_at.is_some() {
        let _: Result<(), _> = redis.del(&key).await;
        return Err(AppError::new(StatusCode::FORBIDDEN, "Account is deleted"));
    }
    if row.suspended_at.is_some() {
        if row.deletion_scheduled_at.is_some() {
            // 削除猶予期間中: セッションは保持し、特別なレスポンスを返す。
            return Err(
                AppError::new(StatusCode::FORBIDDEN, "Account deletion is pending").with_header(
                    header::HeaderName::from_static("x-deletion-pending"),
                    HeaderValue::from_static("true"),
                ),
            );
        }
        let _: Result<(), _> = redis.del(&key).await;
        return Err(AppError::new(StatusCode::FORBIDDEN, "Account is suspended"));
    }
    if row.approval_status == "pending" {
        let _: Result<(), _> = redis.del(&key).await;
        return Err(AppError::new(
            StatusCode::FORBIDDEN,
            "Your registration is pending approval",
        ));
    }

    Ok(CurrentUser {
        id: row.id,
        actor_id: row.actor_id,
        oauth_scopes: None,
    })
}
