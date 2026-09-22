//! `app/api/admin.py` のうち `domain_blocks` 系(`list_domain_blocks`/
//! `create_domain_block`/`remove_domain_block`)、通報系(`get_reports`/
//! `resolve_report`/`reject_report`)、投稿モデレーション系
//! (`admin_delete_note`/`force_note_sensitive`)、モデレーションログ
//! (`get_moderation_log`)を移植したもの。`domain_blocks`はいずれも
//! `get_permitted_staff("domains")`(`admin_auth::require_permission`)配下で、
//! Stage 2 (media proxy) 由来の `domain_block::is_domain_blocked` キャッシュを
//! 書き込み時に無効化する必要がある(Python版の
//! `valkey.delete(f"domain_block:{domain}")`と同じ)。通報系は
//! `get_permitted_staff("reports")`、投稿モデレーション系は
//! `get_permitted_staff("content")`配下で、後者は対象ノートの投稿者が
//! ローカル登録ユーザーの場合`_check_moderation_permission`(スタッフ保護)
//! も課す。モデレーションログは`get_moderation_staff`
//! (`admin_auth::require_moderation_staff`、モデレーター権限を何か1つでも
//! 持てば閲覧可)配下。`admin_delete_note`のフォロワーへのDelete配送は
//! `delete_status`(#1154)と同型(`render_delete_activity`+
//! `get_follower_inboxes`+`enqueue_delivery`)。他の管理エンドポイント
//! (users/emoji等)は本PRのスコープ外、必要になった時点で追加する。

use axum::body::Bytes;
use axum::extract::{Path, Query, State};
use axum::http::{Method, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{delete, get, post};
use axum::{Json, Router};
use chrono::{DateTime, Utc};
use serde::Deserialize;
use serde_json::{json, Value};
use uuid::Uuid;

use crate::activitypub::render_delete_activity;
use crate::admin_auth::{require_moderation_staff, require_permission};
use crate::auth::CurrentUser;
use crate::db;
use crate::delivery::enqueue_delivery;
use crate::domain_block::invalidate_domain_block_cache;
use crate::error::AppError;
use crate::follows::get_follower_inboxes;
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
        .route("/api/v1/admin/reports", get(list_reports))
        .route("/api/v1/admin/reports/:id/resolve", post(resolve_report))
        .route("/api/v1/admin/reports/:id/reject", post(reject_report))
        .route("/api/v1/admin/notes/:id", delete(admin_delete_note))
        .route(
            "/api/v1/admin/notes/:id/sensitive",
            post(force_note_sensitive),
        )
        .route("/api/v1/admin/log", get(get_moderation_log))
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

#[derive(sqlx::FromRow)]
struct ReportRow {
    id: Uuid,
    reporter_username: String,
    reporter_domain: Option<String>,
    target_username: String,
    target_domain: Option<String>,
    target_note_id: Option<Uuid>,
    comment: Option<String>,
    status: String,
    created_at: DateTime<Utc>,
    resolved_at: Option<DateTime<Utc>>,
}

/// `username + ("@" + domain if domain else "")`(`app.api.admin.get_reports`)
/// を移植したもの。
fn acct(username: &str, domain: Option<&str>) -> String {
    match domain {
        Some(domain) => format!("{username}@{domain}"),
        None => username.to_string(),
    }
}

/// `app.schemas.admin.ReportResponse` を移植したもの。
fn report_json(row: &ReportRow) -> Value {
    json!({
        "id": row.id,
        "reporter": acct(&row.reporter_username, row.reporter_domain.as_deref()),
        "target": acct(&row.target_username, row.target_domain.as_deref()),
        "target_note_id": row.target_note_id,
        "comment": row.comment,
        "status": row.status,
        "created_at": to_pydantic_isoformat(row.created_at),
        "resolved_at": row.resolved_at.map(to_pydantic_isoformat),
    })
}

#[derive(Deserialize)]
struct ReportsQuery {
    status: Option<String>,
}

async fn list_reports(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Query(params): Query<ReportsQuery>,
) -> Result<Response, AppError> {
    require_permission(&state, &current_user, &method, "reports").await?;

    let rows: Vec<ReportRow> = sqlx::query_as(
        "SELECT r.id, \
                ra.username AS reporter_username, ra.domain AS reporter_domain, \
                ta.username AS target_username, ta.domain AS target_domain, \
                r.target_note_id, r.comment, r.status, r.created_at, r.resolved_at \
         FROM reports r \
         JOIN actors ra ON ra.id = r.reporter_actor_id \
         JOIN actors ta ON ta.id = r.target_actor_id \
         WHERE $1::text IS NULL OR r.status = $1 \
         ORDER BY r.created_at DESC",
    )
    .bind(&params.status)
    .fetch_all(&state.db)
    .await?;

    Ok(Json(rows.iter().map(report_json).collect::<Vec<_>>()).into_response())
}

async fn fetch_report_status(
    db: &sqlx::PgPool,
    report_id: Uuid,
) -> Result<Option<String>, AppError> {
    let status: Option<String> = sqlx::query_scalar("SELECT status FROM reports WHERE id = $1")
        .bind(report_id)
        .fetch_optional(db)
        .await?;
    Ok(status)
}

async fn resolve_report(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Path(report_id): Path<Uuid>,
) -> Result<Response, AppError> {
    require_permission(&state, &current_user, &method, "reports").await?;

    let status = fetch_report_status(&state.db, report_id)
        .await?
        .ok_or_else(|| AppError::not_found("Report not found"))?;
    if status != "open" {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Report already handled",
        ));
    }

    sqlx::query(
        "UPDATE reports SET status = 'resolved', resolved_by_id = $1, resolved_at = now() \
         WHERE id = $2",
    )
    .bind(current_user.id)
    .bind(report_id)
    .execute(&state.db)
    .await?;

    log_action(
        &state,
        current_user.id,
        "resolve_report",
        "report",
        &report_id.to_string(),
        None,
    )
    .await?;

    Ok(Json(json!({ "ok": true })).into_response())
}

async fn reject_report(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Path(report_id): Path<Uuid>,
) -> Result<Response, AppError> {
    require_permission(&state, &current_user, &method, "reports").await?;

    let status = fetch_report_status(&state.db, report_id)
        .await?
        .ok_or_else(|| AppError::not_found("Report not found"))?;
    if status != "open" {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Report already handled",
        ));
    }

    sqlx::query(
        "UPDATE reports SET status = 'rejected', resolved_by_id = $1, resolved_at = now() \
         WHERE id = $2",
    )
    .bind(current_user.id)
    .bind(report_id)
    .execute(&state.db)
    .await?;

    log_action(
        &state,
        current_user.id,
        "reject_report",
        "report",
        &report_id.to_string(),
        None,
    )
    .await?;

    Ok(Json(json!({ "ok": true })).into_response())
}

#[derive(Deserialize, Default)]
struct ModerationActionRequest {
    reason: Option<String>,
}

/// `app.schemas.admin.ModerationActionRequest`(`Body`がFastAPIの
/// デフォルト引数扱いで省略可能)を移植したもの。空ボディは
/// `reason: None`として扱う。
fn parse_moderation_action(body: &Bytes) -> Result<ModerationActionRequest, AppError> {
    if body.is_empty() {
        return Ok(ModerationActionRequest::default());
    }
    let parsed: ModerationActionRequest = serde_json::from_slice(body).map_err(|e| {
        AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            format!("Invalid request body: {e}"),
        )
    })?;
    if let Some(reason) = &parsed.reason {
        if reason.chars().count() > 2000 {
            return Err(AppError::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "reason must be at most 2000 characters",
            ));
        }
    }
    Ok(parsed)
}

#[derive(sqlx::FromRow)]
struct ModeratableNoteRow {
    actor_id: Uuid,
    ap_id: String,
    local: bool,
    target_role: Option<String>,
}

async fn fetch_note_for_moderation(
    db: &sqlx::PgPool,
    note_id: Uuid,
) -> Result<Option<ModeratableNoteRow>, AppError> {
    let row = sqlx::query_as(
        "SELECT n.actor_id, n.ap_id, n.local, u.role AS target_role \
         FROM notes n \
         LEFT JOIN users u ON u.actor_id = n.actor_id \
         WHERE n.id = $1 AND n.deleted_at IS NULL",
    )
    .bind(note_id)
    .fetch_optional(db)
    .await?;
    Ok(row)
}

/// `app.api.admin._check_moderation_permission` を移植したもの。管理者
/// (`role == "admin"`)は常に許可、対象がスタッフ(`role != "user"`)なら
/// 非管理者モデレーターからのアクションを拒否する。対象がローカル登録
/// ユーザーを持たない(リモートアクター等)場合は`target_role`が`None`に
/// なり、Python版の`if note.actor and note.actor.local_user:`ガードと
/// 同様にチェック自体をスキップする。
async fn check_moderation_permission(
    state: &AppState,
    current_user: &CurrentUser,
    target_role: Option<&str>,
) -> Result<(), AppError> {
    let Some(target_role) = target_role else {
        return Ok(());
    };
    if target_role == "user" {
        return Ok(());
    }
    let acting_role: String = sqlx::query_scalar("SELECT role FROM users WHERE id = $1")
        .bind(current_user.id)
        .fetch_one(&state.db)
        .await?;
    if acting_role == "admin" {
        return Ok(());
    }
    Err(AppError::new(
        StatusCode::FORBIDDEN,
        "Moderators cannot take action against staff members",
    ))
}

/// `app.services.moderation_service.admin_delete_note` を移植したもの。
async fn admin_delete_note(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Path(note_id): Path<Uuid>,
    body: Bytes,
) -> Result<Response, AppError> {
    require_permission(&state, &current_user, &method, "content").await?;
    let action = parse_moderation_action(&body)?;

    let note = fetch_note_for_moderation(&state.db, note_id)
        .await?
        .ok_or_else(|| AppError::not_found("Note not found"))?;
    check_moderation_permission(&state, &current_user, note.target_role.as_deref()).await?;

    sqlx::query("UPDATE notes SET deleted_at = now() WHERE id = $1")
        .bind(note_id)
        .execute(&state.db)
        .await?;

    log_action(
        &state,
        current_user.id,
        "delete_note",
        "note",
        &note_id.to_string(),
        action.reason.as_deref(),
    )
    .await?;

    if note.local {
        let username: String = sqlx::query_scalar("SELECT username FROM actors WHERE id = $1")
            .bind(note.actor_id)
            .fetch_one(&state.db)
            .await?;
        let actor_uri = format!("{}/users/{username}", state.config.server_url());
        let delete_activity =
            render_delete_activity(&format!("{}/delete", note.ap_id), &actor_uri, &note.ap_id);
        for inbox_url in get_follower_inboxes(&state.db, note.actor_id).await? {
            enqueue_delivery(&state, note.actor_id, &inbox_url, &delete_activity).await?;
        }
    }

    Ok(Json(json!({ "ok": true })).into_response())
}

/// `app.services.moderation_service.force_sensitive` を移植したもの。
async fn force_note_sensitive(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Path(note_id): Path<Uuid>,
) -> Result<Response, AppError> {
    require_permission(&state, &current_user, &method, "content").await?;

    let note = fetch_note_for_moderation(&state.db, note_id)
        .await?
        .ok_or_else(|| AppError::not_found("Note not found"))?;
    check_moderation_permission(&state, &current_user, note.target_role.as_deref()).await?;

    sqlx::query("UPDATE notes SET sensitive = true WHERE id = $1")
        .bind(note_id)
        .execute(&state.db)
        .await?;

    log_action(
        &state,
        current_user.id,
        "force_sensitive",
        "note",
        &note_id.to_string(),
        None,
    )
    .await?;

    Ok(Json(json!({ "ok": true })).into_response())
}

#[derive(sqlx::FromRow)]
struct ModerationLogRow {
    id: Uuid,
    moderator: String,
    action: String,
    target_type: String,
    target_id: String,
    reason: Option<String>,
    created_at: DateTime<Utc>,
}

/// `app.schemas.admin.ModerationLogResponse` を移植したもの。
fn moderation_log_json(row: &ModerationLogRow) -> Value {
    json!({
        "id": row.id,
        "moderator": row.moderator,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "reason": row.reason,
        "created_at": to_pydantic_isoformat(row.created_at),
    })
}

#[derive(Deserialize)]
struct LogQuery {
    limit: Option<i64>,
}

/// `Query(default=50, ge=1, le=100)`(FastAPI)の範囲検証を移植したもの。
fn validate_log_limit(limit: Option<i64>) -> Result<i64, AppError> {
    let limit = limit.unwrap_or(50);
    if !(1..=100).contains(&limit) {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "limit must be between 1 and 100",
        ));
    }
    Ok(limit)
}

async fn get_moderation_log(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Query(params): Query<LogQuery>,
) -> Result<Response, AppError> {
    require_moderation_staff(&state, &current_user, &method).await?;
    let limit = validate_log_limit(params.limit)?;

    let rows: Vec<ModerationLogRow> = sqlx::query_as(
        "SELECT l.id, COALESCE(a.username, 'unknown') AS moderator, l.action, l.target_type, \
                l.target_id, l.reason, l.created_at \
         FROM moderation_log l \
         LEFT JOIN users u ON u.id = l.moderator_id \
         LEFT JOIN actors a ON a.id = u.actor_id \
         ORDER BY l.created_at DESC \
         LIMIT $1",
    )
    .bind(limit)
    .fetch_all(&state.db)
    .await?;

    Ok(Json(rows.iter().map(moderation_log_json).collect::<Vec<_>>()).into_response())
}
