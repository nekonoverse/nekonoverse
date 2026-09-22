//! `app/api/admin.py` のうち `domain_blocks` 系(`list_domain_blocks`/
//! `create_domain_block`/`remove_domain_block`)を移植したもの。いずれも
//! `get_permitted_staff("domains")`(`admin_auth::require_permission`)配下で、
//! Stage 2 (media proxy) 由来の `domain_block::is_domain_blocked` キャッシュを
//! 書き込み時に無効化する必要がある(Python版の
//! `valkey.delete(f"domain_block:{domain}")`と同じ)。他の管理エンドポイント
//! (users/reports/emoji等)は本PRのスコープ外、必要になった時点で追加する。

use axum::extract::{Path, State};
use axum::http::{Method, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{delete, get};
use axum::{Json, Router};
use chrono::{DateTime, Utc};
use serde::Deserialize;
use serde_json::{json, Value};
use uuid::Uuid;

use crate::admin_auth::require_permission;
use crate::auth::CurrentUser;
use crate::db;
use crate::domain_block::invalidate_domain_block_cache;
use crate::error::AppError;
use crate::mastodon_time::to_pydantic_isoformat;
use crate::moderation::log_action;
use crate::state::AppState;

pub fn router() -> Router<AppState> {
    Router::new()
        .route(
            "/api/v1/admin/domain_blocks",
            get(list_domain_blocks).post(create_domain_block),
        )
        .route(
            "/api/v1/admin/domain_blocks/:domain",
            delete(remove_domain_block),
        )
}

#[derive(sqlx::FromRow)]
struct DomainBlockRow {
    id: Uuid,
    domain: String,
    severity: String,
    reason: Option<String>,
    created_at: DateTime<Utc>,
}

/// `app.schemas.admin.DomainBlockResponse` を移植したもの
/// (`model_config = {"from_attributes": True}`の素のpydantic datetime直列化)。
fn domain_block_json(row: &DomainBlockRow) -> Value {
    json!({
        "id": row.id,
        "domain": row.domain,
        "severity": row.severity,
        "reason": row.reason,
        "created_at": to_pydantic_isoformat(row.created_at),
    })
}

async fn list_domain_blocks(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
) -> Result<Response, AppError> {
    require_permission(&state, &current_user, &method, "domains").await?;

    let rows: Vec<DomainBlockRow> = sqlx::query_as(
        "SELECT id, domain, severity, reason, created_at FROM domain_blocks ORDER BY created_at DESC",
    )
    .fetch_all(&state.db)
    .await?;

    Ok(Json(rows.iter().map(domain_block_json).collect::<Vec<_>>()).into_response())
}

#[derive(Deserialize)]
struct DomainBlockRequest {
    domain: String,
    #[serde(default = "default_severity")]
    severity: String,
    #[serde(default)]
    reason: Option<String>,
}

fn default_severity() -> String {
    "suspend".to_string()
}

/// `app.schemas.admin.DomainBlockRequest`の`Field`制約を移植したもの。
fn validate_domain_block_request(body: &DomainBlockRequest) -> Result<(), AppError> {
    let domain_len = body.domain.chars().count();
    if !(1..=255).contains(&domain_len) {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "domain must be between 1 and 255 characters",
        ));
    }
    if body.severity != "suspend" && body.severity != "silence" {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "severity must be 'suspend' or 'silence'",
        ));
    }
    if let Some(reason) = &body.reason {
        if reason.chars().count() > 2000 {
            return Err(AppError::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "reason must be at most 2000 characters",
            ));
        }
    }
    Ok(())
}

async fn create_domain_block(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Json(body): Json<DomainBlockRequest>,
) -> Result<Response, AppError> {
    require_permission(&state, &current_user, &method, "domains").await?;
    validate_domain_block_request(&body)?;

    let domain = body.domain.trim().to_lowercase();
    let id = db::new_id();
    let now = db::now();

    let inserted = sqlx::query(
        "INSERT INTO domain_blocks (id, domain, severity, reason, created_by_id, created_at) \
         VALUES ($1, $2, $3, $4, $5, $6)",
    )
    .bind(id)
    .bind(&domain)
    .bind(&body.severity)
    .bind(&body.reason)
    .bind(current_user.id)
    .bind(now)
    .execute(&state.db)
    .await;

    // Python版も`try/except Exception`という広い捕捉だが、実際に起こりうるのは
    // `domain`のUNIQUE制約違反のみ(既にブロック済み)。
    if inserted.is_err() {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Domain already blocked",
        ));
    }

    invalidate_domain_block_cache(&state, &domain).await?;
    log_action(
        &state,
        current_user.id,
        "domain_block",
        "domain",
        &domain,
        body.reason.as_deref(),
    )
    .await?;

    let row = DomainBlockRow {
        id,
        domain,
        severity: body.severity,
        reason: body.reason,
        created_at: now,
    };
    Ok((StatusCode::CREATED, Json(domain_block_json(&row))).into_response())
}

async fn remove_domain_block(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Path(domain): Path<String>,
) -> Result<Response, AppError> {
    require_permission(&state, &current_user, &method, "domains").await?;

    let domain = domain.trim().to_lowercase();
    let result = sqlx::query("DELETE FROM domain_blocks WHERE domain = $1")
        .bind(&domain)
        .execute(&state.db)
        .await?;
    if result.rows_affected() == 0 {
        return Err(AppError::not_found("Domain block not found"));
    }

    invalidate_domain_block_cache(&state, &domain).await?;
    log_action(
        &state,
        current_user.id,
        "domain_unblock",
        "domain",
        &domain,
        None,
    )
    .await?;

    Ok(Json(json!({ "ok": true })).into_response())
}
