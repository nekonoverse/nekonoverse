//! `app/dependencies.py` の `get_permitted_staff(permission)` (と、その内部で
//! 呼ばれる `_require_admin_scope`) を移植したもの。`auth::CurrentUser`で
//! 認証済みのユーザーに対し、管理系ハンドラー本体の先頭で
//! `require_permission(&state, &current_user, &method, "domains").await?`
//! のように呼ぶ(`CurrentUser::require_scope`と同じ利用パターン)。
//!
//! `get_moderation_staff`(`has_any_permission`経由でモデレーター権限を何か
//! 1つでも持つか確認する版、`GET /api/v1/admin/log`が使う)、`get_admin_user`
//! (`role == "admin"`のみ許可、`roles` CRUD系が使う)、`get_staff_user`
//! (`role != "user"`なら許可、`GET /api/v1/admin/permissions`が使う)も移植済み。

use axum::http::{Method, StatusCode};
use serde_json::Value;
use sqlx::PgPool;

use crate::auth::CurrentUser;
use crate::error::AppError;
use crate::state::AppState;

/// `app.dependencies._require_admin_scope` を移植したもの。セッション認証
/// (`oauth_scopes`が`None`)は対象外、OAuthトークン認証時のみ
/// `admin:read`/`admin:write`スコープを要求する。
fn require_admin_scope(current_user: &CurrentUser, method: &Method) -> Result<(), AppError> {
    let Some(scopes) = &current_user.oauth_scopes else {
        return Ok(());
    };
    let needed = if matches!(*method, Method::GET | Method::HEAD | Method::OPTIONS) {
        "admin:read"
    } else {
        "admin:write"
    };
    if scopes
        .iter()
        .any(|s| s == needed || s.starts_with(&format!("{needed}:")))
    {
        return Ok(());
    }
    Err(AppError::new(
        StatusCode::FORBIDDEN,
        format!("Insufficient scope: {needed} required"),
    ))
}

#[derive(sqlx::FromRow)]
struct RolePermissionsRow {
    is_admin: bool,
    permissions: Option<Value>,
}

async fn fetch_role(db: &PgPool, role_name: &str) -> Result<Option<RolePermissionsRow>, AppError> {
    let row = sqlx::query_as("SELECT is_admin, permissions FROM roles WHERE name = $1")
        .bind(role_name)
        .fetch_optional(db)
        .await?;
    Ok(row)
}

/// `app.dependencies.get_permitted_staff(permission)` を移植したもの。
/// `user.is_admin`(`role == "admin"`)は常に許可、`role == "user"`(非staff)は
/// 常に拒否、それ以外は`roles`テーブルの`is_admin`列または
/// `permissions`JSONBの該当キーで判定する。
pub async fn require_permission(
    state: &AppState,
    current_user: &CurrentUser,
    method: &Method,
    permission: &str,
) -> Result<(), AppError> {
    let role: String = sqlx::query_scalar("SELECT role FROM users WHERE id = $1")
        .bind(current_user.id)
        .fetch_one(&state.db)
        .await?;

    if role == "admin" {
        require_admin_scope(current_user, method)?;
        return Ok(());
    }
    if role == "user" {
        return Err(AppError::new(
            StatusCode::FORBIDDEN,
            "Staff access required",
        ));
    }

    require_admin_scope(current_user, method)?;

    let Some(role_row) = fetch_role(&state.db, &role).await? else {
        return Err(AppError::new(StatusCode::FORBIDDEN, "Permission denied"));
    };
    if role_row.is_admin {
        return Ok(());
    }
    let allowed = role_row
        .permissions
        .as_ref()
        .and_then(|p| p.get(permission))
        .and_then(Value::as_bool)
        .unwrap_or(false);
    if allowed {
        Ok(())
    } else {
        Err(AppError::new(StatusCode::FORBIDDEN, "Permission denied"))
    }
}

/// `app.services.role_service.MODERATOR_PERMISSIONS` を移植したもの。
const MODERATOR_PERMISSIONS: [&str; 8] = [
    "users",
    "reports",
    "content",
    "domains",
    "federation",
    "emoji",
    "registrations",
    "announcements",
];

/// `app.dependencies.get_moderation_staff` (`get_staff_user` + `has_any_permission`)
/// を移植したもの。`role == "admin"`は常に許可、`role == "user"`は常に拒否、
/// それ以外は`roles.is_admin`列またはモデレーター権限リストのいずれか1つが
/// `permissions` JSONBで真であれば許可する。
pub async fn require_moderation_staff(
    state: &AppState,
    current_user: &CurrentUser,
    method: &Method,
) -> Result<(), AppError> {
    let role: String = sqlx::query_scalar("SELECT role FROM users WHERE id = $1")
        .bind(current_user.id)
        .fetch_one(&state.db)
        .await?;

    if role == "user" {
        return Err(AppError::new(StatusCode::FORBIDDEN, "Staff only"));
    }
    require_admin_scope(current_user, method)?;
    if role == "admin" {
        return Ok(());
    }

    let Some(role_row) = fetch_role(&state.db, &role).await? else {
        return Err(AppError::new(StatusCode::FORBIDDEN, "Permission denied"));
    };
    if role_row.is_admin {
        return Ok(());
    }
    let allowed = role_row.permissions.as_ref().is_some_and(|p| {
        MODERATOR_PERMISSIONS
            .iter()
            .any(|perm| p.get(*perm).and_then(Value::as_bool).unwrap_or(false))
    });
    if allowed {
        Ok(())
    } else {
        Err(AppError::new(StatusCode::FORBIDDEN, "Permission denied"))
    }
}

/// `app.dependencies.get_admin_user` を移植したもの。`role == "admin"`のみ
/// 許可する(カスタムroleの`roles.is_admin`列は見ない、Python版と同じ)。
pub async fn require_admin_role(
    state: &AppState,
    current_user: &CurrentUser,
    method: &Method,
) -> Result<(), AppError> {
    let role: String = sqlx::query_scalar("SELECT role FROM users WHERE id = $1")
        .bind(current_user.id)
        .fetch_one(&state.db)
        .await?;
    if role != "admin" {
        return Err(AppError::new(StatusCode::FORBIDDEN, "Admin only"));
    }
    require_admin_scope(current_user, method)
}

/// `app.dependencies.get_staff_user` を移植したもの。`role != "user"`であれば
/// 許可する(具体的な権限は見ない)。
pub async fn require_staff(
    state: &AppState,
    current_user: &CurrentUser,
    method: &Method,
) -> Result<(), AppError> {
    let role: String = sqlx::query_scalar("SELECT role FROM users WHERE id = $1")
        .bind(current_user.id)
        .fetch_one(&state.db)
        .await?;
    if role == "user" {
        return Err(AppError::new(StatusCode::FORBIDDEN, "Staff only"));
    }
    require_admin_scope(current_user, method)
}
