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
//! `get_follower_inboxes`+`enqueue_delivery`)。ロール管理系(`list_roles`/
//! `get_role`/`create_role`/`update_role`/`delete_role`)は`get_admin_user`
//! (`admin_auth::require_admin_role`)配下、レガシーのモデレーター権限
//! ショートカット(`get_permissions`/`update_permissions`、"moderator" role の
//! `permissions`のうち`role_service.MODERATOR_PERMISSIONS`とは異なり
//! "announcements"を含まない7キーだけを読み書きする
//! `permission_service.MODERATOR_PERMISSIONS`が対象)はGETが`get_staff_user`
//! (`require_staff`)、PATCHが`get_admin_user`(`require_admin_role`)配下。
//! ユーザー管理系(`list_users`/`change_user_role`/`suspend_user`/
//! `unsuspend_user`/`silence_user`/`unsilence_user`)は`list_users`/
//! `suspend_user`/`unsuspend_user`/`silence_user`/`unsilence_user`が
//! `get_permitted_staff("users")`(`require_permission`)、
//! `change_user_role`のみ`get_admin_user`(`require_admin_role`)配下。
//! いずれも対象は`is_system`(システムアカウント)不可、`suspend`/`silence`/
//! `change_user_role`はさらに操作対象が自分自身なら拒否する。停止/サイレンス
//! 系は投稿モデレーション系と同じ`check_moderation_permission`
//! (非admin一般モデレーターはスタッフ保護対象に手を出せない)を課す。
//! `admin_delete_user`(アカウント即時削除、`account_deletion_service.
//! admin_force_delete`経由でフォロー整理・メディア削除・Undo Follow配送・
//! Delete(Person)配送を伴う大きめの一枚岩)は本PRのスコープ外、
//! 他の管理エンドポイント(emoji/announcements/queue/system統計等)と合わせ
//! 必要になった時点で追加する。

use axum::body::Bytes;
use axum::extract::{Path, Query, State};
use axum::http::{Method, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{delete, get, patch, post};
use axum::{Json, Router};
use chrono::{DateTime, Utc};
use serde::Deserialize;
use serde_json::{json, Map, Value};
use uuid::Uuid;

use crate::activitypub::render_delete_activity;
use crate::admin_auth::{
    require_admin_role, require_moderation_staff, require_permission, require_staff,
};
use crate::auth::CurrentUser;
use crate::db;
use crate::delivery::enqueue_delivery;
use crate::domain_block::invalidate_domain_block_cache;
use crate::error::AppError;
use crate::follows::get_follower_inboxes;
use crate::mastodon_time::to_pydantic_isoformat;
use crate::moderation::{self, log_action};
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
        .route("/api/v1/admin/roles", get(list_roles).post(create_role))
        .route(
            "/api/v1/admin/roles/:name",
            get(get_role).patch(update_role).delete(delete_role),
        )
        .route(
            "/api/v1/admin/permissions",
            get(get_permissions).patch(update_permissions),
        )
        .route("/api/v1/admin/users", get(list_users))
        .route("/api/v1/admin/users/:id/role", patch(change_user_role))
        .route("/api/v1/admin/users/:id/suspend", post(suspend_user))
        .route("/api/v1/admin/users/:id/unsuspend", post(unsuspend_user))
        .route("/api/v1/admin/users/:id/silence", post(silence_user))
        .route("/api/v1/admin/users/:id/unsilence", post(unsilence_user))
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

#[derive(sqlx::FromRow)]
struct RoleRow {
    name: String,
    display_name: String,
    permissions: Value,
    is_admin: bool,
    quota_bytes: i64,
    priority: i32,
    is_system: bool,
    created_at: DateTime<Utc>,
}

/// `app.schemas.admin.RoleResponse` を移植したもの。
fn role_json(row: &RoleRow) -> Value {
    json!({
        "name": row.name,
        "display_name": row.display_name,
        "permissions": row.permissions,
        "is_admin": row.is_admin,
        "quota_bytes": row.quota_bytes,
        "priority": row.priority,
        "is_system": row.is_system,
        "created_at": to_pydantic_isoformat(row.created_at),
    })
}

async fn fetch_role_row(db: &sqlx::PgPool, name: &str) -> Result<Option<RoleRow>, AppError> {
    let row = sqlx::query_as(
        "SELECT name, display_name, permissions, is_admin, quota_bytes, priority, is_system, \
                created_at \
         FROM roles WHERE name = $1",
    )
    .bind(name)
    .fetch_optional(db)
    .await?;
    Ok(row)
}

async fn list_roles(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
) -> Result<Response, AppError> {
    require_admin_role(&state, &current_user, &method).await?;

    let rows: Vec<RoleRow> = sqlx::query_as(
        "SELECT name, display_name, permissions, is_admin, quota_bytes, priority, is_system, \
                created_at \
         FROM roles ORDER BY priority DESC, name",
    )
    .fetch_all(&state.db)
    .await?;

    Ok(Json(rows.iter().map(role_json).collect::<Vec<_>>()).into_response())
}

async fn get_role(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Path(name): Path<String>,
) -> Result<Response, AppError> {
    require_admin_role(&state, &current_user, &method).await?;

    let row = fetch_role_row(&state.db, &name)
        .await?
        .ok_or_else(|| AppError::not_found("Role not found"))?;
    Ok(Json(role_json(&row)).into_response())
}

#[derive(Deserialize)]
struct RoleCreateRequest {
    name: String,
    display_name: String,
    copy_from: Option<String>,
}

/// `app.schemas.admin.RoleCreateRequest`の`Field`制約を移植したもの。
fn validate_role_create(body: &RoleCreateRequest) -> Result<(), AppError> {
    let name_len = body.name.chars().count();
    let valid_name = (1..=50).contains(&name_len)
        && body
            .name
            .chars()
            .next()
            .is_some_and(|c| c.is_ascii_lowercase())
        && body
            .name
            .chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_');
    if !valid_name {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "name must match ^[a-z][a-z0-9_]*$ and be at most 50 characters",
        ));
    }
    let display_len = body.display_name.chars().count();
    if !(1..=100).contains(&display_len) {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "display_name must be between 1 and 100 characters",
        ));
    }
    Ok(())
}

/// `app.services.role_service.create_role` を移植したもの。
async fn create_role(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Json(body): Json<RoleCreateRequest>,
) -> Result<Response, AppError> {
    require_admin_role(&state, &current_user, &method).await?;
    validate_role_create(&body)?;

    if fetch_role_row(&state.db, &body.name).await?.is_some() {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            format!("Role '{}' already exists", body.name),
        ));
    }

    let (permissions, quota_bytes, priority) = match &body.copy_from {
        Some(copy_from) => match fetch_role_row(&state.db, copy_from).await? {
            Some(source) => (source.permissions, source.quota_bytes, source.priority),
            None => (json!({}), 1_073_741_824i64, 0i32),
        },
        None => (json!({}), 1_073_741_824i64, 0i32),
    };

    sqlx::query(
        "INSERT INTO roles (name, display_name, permissions, quota_bytes, priority, is_system) \
         VALUES ($1, $2, $3, $4, $5, false)",
    )
    .bind(&body.name)
    .bind(&body.display_name)
    .bind(sqlx::types::Json(&permissions))
    .bind(quota_bytes)
    .bind(priority)
    .execute(&state.db)
    .await?;

    let row = fetch_role_row(&state.db, &body.name)
        .await?
        .ok_or_else(|| AppError::new(StatusCode::INTERNAL_SERVER_ERROR, "Internal server error"))?;
    Ok((StatusCode::CREATED, Json(role_json(&row))).into_response())
}

#[derive(Deserialize)]
struct RoleUpdateRequest {
    display_name: Option<String>,
    permissions: Option<Value>,
    quota_bytes: Option<i64>,
    priority: Option<i32>,
}

/// `app.schemas.admin.RoleUpdateRequest`の`Field`制約を移植したもの。
fn validate_role_update(body: &RoleUpdateRequest) -> Result<(), AppError> {
    if let Some(display_name) = &body.display_name {
        let len = display_name.chars().count();
        if !(1..=100).contains(&len) {
            return Err(AppError::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "display_name must be between 1 and 100 characters",
            ));
        }
    }
    if let Some(quota_bytes) = body.quota_bytes {
        if quota_bytes < 0 {
            return Err(AppError::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "quota_bytes must be greater than or equal to 0",
            ));
        }
    }
    Ok(())
}

/// `app.services.role_service.update_role` を移植したもの。`is_system`な
/// role(admin/user/moderator)も含め、`display_name`/`permissions`/
/// `quota_bytes`/`priority`のうち渡されたフィールドだけを更新する
/// (Python版に`is_system`ガードは無い、削除のみ禁止)。
async fn update_role(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Path(name): Path<String>,
    Json(body): Json<RoleUpdateRequest>,
) -> Result<Response, AppError> {
    require_admin_role(&state, &current_user, &method).await?;
    validate_role_update(&body)?;

    if fetch_role_row(&state.db, &name).await?.is_none() {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            format!("Role '{name}' not found"),
        ));
    }

    sqlx::query(
        "UPDATE roles SET \
            display_name = COALESCE($1, display_name), \
            permissions = COALESCE($2, permissions), \
            quota_bytes = COALESCE($3, quota_bytes), \
            priority = COALESCE($4, priority) \
         WHERE name = $5",
    )
    .bind(&body.display_name)
    .bind(body.permissions.as_ref().map(sqlx::types::Json))
    .bind(body.quota_bytes)
    .bind(body.priority)
    .bind(&name)
    .execute(&state.db)
    .await?;

    let row = fetch_role_row(&state.db, &name)
        .await?
        .ok_or_else(|| AppError::new(StatusCode::INTERNAL_SERVER_ERROR, "Internal server error"))?;
    Ok(Json(role_json(&row)).into_response())
}

/// `app.services.role_service.delete_role` を移植したもの。未発見・
/// 組み込みrole・割り当て中ユーザーありのいずれも(404ではなく)422で
/// 返す、Python版が`ValueError`を422にマップしているのと同じ。
async fn delete_role(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Path(name): Path<String>,
) -> Result<Response, AppError> {
    require_admin_role(&state, &current_user, &method).await?;

    let role = fetch_role_row(&state.db, &name).await?.ok_or_else(|| {
        AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            format!("Role '{name}' not found"),
        )
    })?;
    if role.is_system {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Cannot delete a built-in role",
        ));
    }

    let user_count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM users WHERE role = $1")
        .bind(&name)
        .fetch_one(&state.db)
        .await?;
    if user_count > 0 {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            format!("Cannot delete role '{name}': {user_count} user(s) assigned"),
        ));
    }

    sqlx::query("DELETE FROM roles WHERE name = $1")
        .bind(&name)
        .execute(&state.db)
        .await?;

    Ok(StatusCode::NO_CONTENT.into_response())
}

/// `app.services.permission_service.MODERATOR_PERMISSIONS` を移植したもの。
/// `admin_auth::MODERATOR_PERMISSIONS`(`role_service`側、8キー)とは異なり
/// "announcements"を含まない7キー。順序もPython版のdictキー順と揃える。
const LEGACY_MODERATOR_PERMISSIONS: [&str; 7] = [
    "users",
    "reports",
    "content",
    "domains",
    "federation",
    "emoji",
    "registrations",
];

/// `app.services.permission_service.get_moderator_permissions` を移植した
/// もの。"moderator" roleが無ければ全キーtrue、あれば各キーごとに
/// `permissions.get(perm, True)`(未設定なら既定でtrue)。
async fn moderator_permissions_json(db: &sqlx::PgPool) -> Result<Value, AppError> {
    let role = fetch_role_row(db, "moderator").await?;
    let mut map = Map::new();
    for perm in LEGACY_MODERATOR_PERMISSIONS {
        let value = role
            .as_ref()
            .and_then(|r| r.permissions.get(perm))
            .and_then(Value::as_bool)
            .unwrap_or(true);
        map.insert(perm.to_string(), Value::Bool(value));
    }
    Ok(Value::Object(map))
}

async fn get_permissions(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
) -> Result<Response, AppError> {
    require_staff(&state, &current_user, &method).await?;
    Ok(Json(moderator_permissions_json(&state.db).await?).into_response())
}

/// Pythonの`bool(value)`真偽変換を移植したもの
/// (`app.services.permission_service.set_moderator_permissions`の
/// `current[key] = bool(value)`)。null/false/0/空文字列/空配列/空オブジェクト
/// はfalse、それ以外はtrue。
fn python_truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().is_some_and(|f| f != 0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

/// `app.services.permission_service.set_moderator_permissions` を移植した
/// もの。"moderator" roleが存在しなければ何もしない(Python版と同じ、
/// is_system=trueのため実運用では起こらない)。未知キーは無視する。
async fn update_permissions(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Json(body): Json<Map<String, Value>>,
) -> Result<Response, AppError> {
    require_admin_role(&state, &current_user, &method).await?;

    if let Some(role) = fetch_role_row(&state.db, "moderator").await? {
        let mut current = match role.permissions {
            Value::Object(map) => map,
            _ => Map::new(),
        };
        for perm in LEGACY_MODERATOR_PERMISSIONS {
            if let Some(value) = body.get(perm) {
                current.insert(perm.to_string(), Value::Bool(python_truthy(value)));
            }
        }
        sqlx::query("UPDATE roles SET permissions = $1 WHERE name = 'moderator'")
            .bind(sqlx::types::Json(Value::Object(current)))
            .execute(&state.db)
            .await?;
    }

    Ok(Json(moderator_permissions_json(&state.db).await?).into_response())
}

#[derive(sqlx::FromRow)]
struct AdminUserRow {
    id: Uuid,
    username: String,
    email: String,
    display_name: Option<String>,
    role: String,
    is_active: bool,
    is_system: bool,
    suspended_at: Option<DateTime<Utc>>,
    silenced_at: Option<DateTime<Utc>>,
    created_at: DateTime<Utc>,
}

/// `app.schemas.admin.AdminUserResponse` を移植したもの。`storage_usage_bytes`
/// はPython版のスキーマ上のデフォルト値(`list_users`は渡さない)で固定。
fn admin_user_json(row: &AdminUserRow) -> Value {
    json!({
        "id": row.id,
        "username": row.username,
        "email": row.email,
        "display_name": row.display_name,
        "role": row.role,
        "is_active": row.is_active,
        "is_system": row.is_system,
        "suspended": row.suspended_at.is_some(),
        "silenced": row.silenced_at.is_some(),
        "storage_usage_bytes": 0,
        "created_at": to_pydantic_isoformat(row.created_at),
    })
}

#[derive(Deserialize)]
struct UsersQuery {
    limit: Option<i64>,
    offset: Option<i64>,
}

/// `Query(default=50, le=100)`/`Query(default=0, ge=0)`(FastAPI、Python版の
/// `list_users`)の範囲検証を移植したもの。Python版は`limit`に下限が無く
/// `offset`に上限が無い、非対称な制約をそのまま踏襲する。
fn validate_users_query(limit: Option<i64>, offset: Option<i64>) -> Result<(i64, i64), AppError> {
    let limit = limit.unwrap_or(50);
    if limit > 100 {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "limit must be at most 100",
        ));
    }
    let offset = offset.unwrap_or(0);
    if offset < 0 {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "offset must be greater than or equal to 0",
        ));
    }
    Ok((limit, offset))
}

async fn list_users(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Query(params): Query<UsersQuery>,
) -> Result<Response, AppError> {
    require_permission(&state, &current_user, &method, "users").await?;
    let (limit, offset) = validate_users_query(params.limit, params.offset)?;

    let rows: Vec<AdminUserRow> = sqlx::query_as(
        "SELECT u.id, a.username, u.email, a.display_name, u.role, u.is_active, u.is_system, \
                a.suspended_at, a.silenced_at, u.created_at \
         FROM users u \
         JOIN actors a ON a.id = u.actor_id \
         ORDER BY u.created_at DESC \
         LIMIT $1 OFFSET $2",
    )
    .bind(limit)
    .bind(offset)
    .fetch_all(&state.db)
    .await?;

    Ok(Json(rows.iter().map(admin_user_json).collect::<Vec<_>>()).into_response())
}

#[derive(sqlx::FromRow)]
struct TargetUserRow {
    id: Uuid,
    actor_id: Uuid,
    username: String,
    role: String,
    is_system: bool,
    suspended_at: Option<DateTime<Utc>>,
    silenced_at: Option<DateTime<Utc>>,
}

/// `app.api.admin._get_user` を移植したもの。
async fn fetch_target_user(
    db: &sqlx::PgPool,
    user_id: Uuid,
) -> Result<Option<TargetUserRow>, AppError> {
    let row = sqlx::query_as(
        "SELECT u.id, u.actor_id, a.username, u.role, u.is_system, a.suspended_at, a.silenced_at \
         FROM users u JOIN actors a ON a.id = u.actor_id WHERE u.id = $1",
    )
    .bind(user_id)
    .fetch_optional(db)
    .await?;
    Ok(row)
}

#[derive(Deserialize)]
struct RoleChangeRequest {
    role: String,
}

/// `app.schemas.admin.RoleChangeRequest`の`Field`制約(`validate_role_create`の
/// name制約と同一パターン)を移植したもの。
fn validate_role_change(body: &RoleChangeRequest) -> Result<(), AppError> {
    let len = body.role.chars().count();
    let valid = (1..=50).contains(&len)
        && body
            .role
            .chars()
            .next()
            .is_some_and(|c| c.is_ascii_lowercase())
        && body
            .role
            .chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_');
    if !valid {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "role must match ^[a-z][a-z0-9_]*$ and be at most 50 characters",
        ));
    }
    Ok(())
}

async fn change_user_role(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Path(user_id): Path<Uuid>,
    Json(body): Json<RoleChangeRequest>,
) -> Result<Response, AppError> {
    require_admin_role(&state, &current_user, &method).await?;
    validate_role_change(&body)?;

    let target = fetch_target_user(&state.db, user_id)
        .await?
        .ok_or_else(|| AppError::not_found("User not found"))?;
    if target.is_system {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Cannot modify system account",
        ));
    }
    if target.id == current_user.id {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Cannot change own role",
        ));
    }
    if fetch_role_row(&state.db, &body.role).await?.is_none() {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            format!("Role '{}' does not exist", body.role),
        ));
    }

    sqlx::query("UPDATE users SET role = $1 WHERE id = $2")
        .bind(&body.role)
        .bind(user_id)
        .execute(&state.db)
        .await?;

    log_action(
        &state,
        current_user.id,
        "role_change",
        "actor",
        &target.actor_id.to_string(),
        Some(&format!("{} -> {}", target.role, body.role)),
    )
    .await?;

    Ok(Json(json!({ "ok": true, "role": body.role })).into_response())
}

async fn suspend_user(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Path(user_id): Path<Uuid>,
    body: Bytes,
) -> Result<Response, AppError> {
    require_permission(&state, &current_user, &method, "users").await?;
    let action = parse_moderation_action(&body)?;

    let target = fetch_target_user(&state.db, user_id)
        .await?
        .ok_or_else(|| AppError::not_found("User not found"))?;
    if target.is_system {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Cannot modify system account",
        ));
    }
    if target.suspended_at.is_some() {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Already suspended",
        ));
    }
    if target.id == current_user.id {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Cannot suspend self",
        ));
    }
    check_moderation_permission(&state, &current_user, Some(&target.role)).await?;

    moderation::suspend_actor(
        &state,
        target.actor_id,
        &target.username,
        target.id,
        current_user.id,
        action.reason.as_deref(),
    )
    .await?;

    Ok(Json(json!({ "ok": true })).into_response())
}

async fn unsuspend_user(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Path(user_id): Path<Uuid>,
) -> Result<Response, AppError> {
    require_permission(&state, &current_user, &method, "users").await?;

    let target = fetch_target_user(&state.db, user_id)
        .await?
        .ok_or_else(|| AppError::not_found("User not found"))?;
    if target.is_system {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Cannot modify system account",
        ));
    }
    if target.suspended_at.is_none() {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Not suspended",
        ));
    }
    check_moderation_permission(&state, &current_user, Some(&target.role)).await?;

    moderation::unsuspend_actor(&state, target.actor_id, current_user.id).await?;

    Ok(Json(json!({ "ok": true })).into_response())
}

async fn silence_user(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Path(user_id): Path<Uuid>,
    body: Bytes,
) -> Result<Response, AppError> {
    require_permission(&state, &current_user, &method, "users").await?;
    let action = parse_moderation_action(&body)?;

    let target = fetch_target_user(&state.db, user_id)
        .await?
        .ok_or_else(|| AppError::not_found("User not found"))?;
    if target.is_system {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Cannot modify system account",
        ));
    }
    if target.silenced_at.is_some() {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Already silenced",
        ));
    }
    if target.id == current_user.id {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Cannot silence self",
        ));
    }
    check_moderation_permission(&state, &current_user, Some(&target.role)).await?;

    moderation::silence_actor(
        &state,
        target.actor_id,
        current_user.id,
        action.reason.as_deref(),
    )
    .await?;

    Ok(Json(json!({ "ok": true })).into_response())
}

async fn unsilence_user(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Path(user_id): Path<Uuid>,
) -> Result<Response, AppError> {
    require_permission(&state, &current_user, &method, "users").await?;

    let target = fetch_target_user(&state.db, user_id)
        .await?
        .ok_or_else(|| AppError::not_found("User not found"))?;
    if target.is_system {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Cannot modify system account",
        ));
    }
    if target.silenced_at.is_none() {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Not silenced",
        ));
    }
    check_moderation_permission(&state, &current_user, Some(&target.role)).await?;

    moderation::unsilence_actor(&state, target.actor_id, current_user.id).await?;

    Ok(Json(json!({ "ok": true })).into_response())
}
