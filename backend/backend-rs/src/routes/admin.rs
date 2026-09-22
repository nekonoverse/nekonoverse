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
//! Delete(Person)配送を伴う大きめの一枚岩)は引き続き未移植、
//! 他の管理エンドポイント(emoji/announcements/system統計等)と合わせ
//! 必要になった時点で追加する。
//!
//! キュー管理系(`get_queue_stats`/`get_queue_jobs`/`retry_job`/
//! `retry_all_dead`/`purge_delivered`、いずれも`app.services.queue_service`)
//! は`get_admin_user`(`admin_auth::require_admin_role`)配下。対象は
//! Stage 4の`delivery.rs`(pin/unpin等のプロデューサ)が書き込むのと同じ
//! `delivery_queue`テーブルで、モデレーションログへの記録は行わない
//! (Python版に該当呼び出しが無いことを確認済み)。`get_queue_stats`の
//! `recent_delivered`/`recent_dead`は変数名に反し「直近1時間」ではなく
//! 「今の時(hour)の開始時刻以降」(`datetime.now(UTC).replace(minute=0,
//! second=0, microsecond=0)`)を境界に使うPython版の実際の挙動をそのまま
//! 踏襲した。
//!
//! 登録承認系(`list_pending_registrations`/`approve_registration`/
//! `reject_registration`)は`get_permitted_staff("registrations")`
//! (`require_permission`)配下。対象は`approval_status == "pending"`の
//! ユーザーのみで、承認は`approval_status`を`"approved"`に更新するだけ、
//! 却下はユーザー本体と紐づくactorを削除する(Python版の
//! `db.delete(target); db.delete(actor)`と同じ、未承認ユーザーはまだ
//! フォロー等の関連行を持ちえないため追加のクリーンアップは不要)。
//! いずれも`is_system`チェックは無い(Python版の`approve_registration`/
//! `reject_registration`が`_get_user`のみで`is_system`を見ていないのと同じ、
//! システムアカウントは`approval_status`が常に`"approved"`のため実質到達不能)。
//!
//! 連合サーバー一覧/詳細(`list_federated_servers`/
//! `get_federated_server_detail_endpoint`、`app.services.federation_service`)は
//! `get_permitted_staff("federation")`(`require_permission`)配下の読み取り
//! 専用エンドポイントで、書き込みや新たな対外通信能力を要しない
//! (`actors`/`notes`/`delivery_queue`/`domain_blocks`の集計クエリのみ)ため、
//! `admin_delete_user`等より先に着手した。`actors.domain`はローカルactorが
//! 常に`NULL`という前提(ドメインブロック等ローカル分岐が無いことから確認済み)
//! でリモートサーバー単位に集約する。`delivery_queue`側は
//! `target_inbox_url`から正規表現(`substring(... from 'https?://([^/]+)')`)で
//! ドメインを抽出する、Python版の`func.substring`と同じ手法。
//!
//! サーバー設定(`get_server_settings`/`update_server_settings`、
//! `app.services.server_settings_service`)、統計(`get_admin_stats`)、
//! システム統計(`get_system_stats`)は`get_admin_user`
//! (`require_admin_role`、`get_admin_stats`のみ`get_permitted_staff("users")`)
//! 配下。`update_server_settings`内の`_resolve_pending_users`
//! (承認制モードから離脱時、承認待ちユーザーを一括承認/却下する処理)は
//! `reject_registration`(#1169)と同じユーザー+actor削除パターンを流用した。
//! VAPID鍵生成(`POST /admin/push/generate-vapid-key`)はPython側の
//! プロセス内メモリキャッシュ(`push_service._cached_db_vapid_key`)と
//! backend-rsが別プロセスであるため生成後の反映タイミングがズレる懸念があり
//! (実際のプッシュ配送は引き続きPython側が担当)、意図的に未移植のまま
//! Python側に残す(`crate::server_settings`のモジュールdoc参照)。
//! `get_server_settings`が返す`vapid_public_key`はDB保存済み秘密鍵からの
//! 純粋な読み取り専用導出のためこの懸念に該当せず、移植済み。
//! `get_system_stats`のDBプール統計はsqlxに`overflow`の概念が無い
//! (SQLAlchemyの`QueuePool.max_overflow`と異なり単一の接続上限のみ)ため
//! `db_pool_overflow`は常に`0`を返す。

use axum::body::Bytes;
use axum::extract::{Path, Query, State};
use axum::http::{Method, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{delete, get, patch, post};
use axum::{Json, Router};
use chrono::{DateTime, Timelike, Utc};
use redis::AsyncCommands;
use serde::Deserialize;
use serde_json::{json, Map, Value};
use std::collections::HashMap;
use uuid::Uuid;

use crate::activitypub::render_delete_activity;
use crate::admin_auth::{
    require_admin_role, require_moderation_staff, require_permission, require_staff,
};
use crate::auth::CurrentUser;
use crate::config::Config;
use crate::db;
use crate::delivery::enqueue_delivery;
use crate::domain_block::invalidate_domain_block_cache;
use crate::error::AppError;
use crate::follows::get_follower_inboxes;
use crate::mastodon_time::to_pydantic_isoformat;
use crate::moderation::{self, log_action};
use crate::server_settings::{get_all_settings, set_setting, vapid_public_key_base64url};
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
        .route("/api/v1/admin/queue/stats", get(get_queue_stats))
        .route("/api/v1/admin/queue/jobs", get(list_queue_jobs))
        .route("/api/v1/admin/queue/retry/:id", post(retry_queue_job))
        .route("/api/v1/admin/queue/retry-all", post(retry_all_dead_jobs))
        .route("/api/v1/admin/queue/purge", delete(purge_delivered_jobs))
        .route(
            "/api/v1/admin/registrations",
            get(list_pending_registrations),
        )
        .route(
            "/api/v1/admin/registrations/:id/approve",
            post(approve_registration),
        )
        .route(
            "/api/v1/admin/registrations/:id/reject",
            post(reject_registration),
        )
        .route("/api/v1/admin/federation", get(list_federated_servers))
        .route(
            "/api/v1/admin/federation/*domain",
            get(get_federated_server_detail_endpoint),
        )
        .route(
            "/api/v1/admin/settings",
            get(get_server_settings).patch(update_server_settings),
        )
        .route("/api/v1/admin/stats", get(get_admin_stats))
        .route("/api/v1/admin/system/stats", get(get_system_stats))
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

#[derive(sqlx::FromRow)]
struct QueueStatsRow {
    pending: i64,
    processing: i64,
    delivered: i64,
    dead: i64,
    recent_delivered: i64,
    recent_dead: i64,
}

/// `app.services.queue_service.get_queue_stats` を移植したもの。
async fn get_queue_stats(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
) -> Result<Response, AppError> {
    require_admin_role(&state, &current_user, &method).await?;

    let hour_start = Utc::now()
        .with_minute(0)
        .unwrap()
        .with_second(0)
        .unwrap()
        .with_nanosecond(0)
        .unwrap();

    let row: QueueStatsRow = sqlx::query_as(
        "SELECT \
            COUNT(*) FILTER (WHERE status = 'pending') AS pending, \
            COUNT(*) FILTER (WHERE status = 'processing') AS processing, \
            COUNT(*) FILTER (WHERE status = 'delivered') AS delivered, \
            COUNT(*) FILTER (WHERE status = 'dead') AS dead, \
            COUNT(*) FILTER (WHERE status = 'delivered' AND last_attempted_at >= $1) AS recent_delivered, \
            COUNT(*) FILTER (WHERE status = 'dead' AND last_attempted_at >= $1) AS recent_dead \
         FROM delivery_queue",
    )
    .bind(hour_start)
    .fetch_one(&state.db)
    .await?;

    Ok(Json(json!({
        "pending": row.pending,
        "processing": row.processing,
        "delivered": row.delivered,
        "dead": row.dead,
        "total": row.pending + row.processing + row.delivered + row.dead,
        "recent_delivered": row.recent_delivered,
        "recent_dead": row.recent_dead,
    }))
    .into_response())
}

#[derive(sqlx::FromRow)]
struct QueueJobRow {
    id: Uuid,
    target_inbox_url: String,
    status: String,
    attempts: i32,
    max_attempts: i32,
    error_message: Option<String>,
    created_at: DateTime<Utc>,
    last_attempted_at: Option<DateTime<Utc>>,
    next_retry_at: Option<DateTime<Utc>>,
}

/// `app.schemas.admin.QueueJobResponse` を移植したもの。
fn queue_job_json(row: &QueueJobRow) -> Value {
    json!({
        "id": row.id,
        "target_inbox_url": row.target_inbox_url,
        "status": row.status,
        "attempts": row.attempts,
        "max_attempts": row.max_attempts,
        "error_message": row.error_message,
        "created_at": to_pydantic_isoformat(row.created_at),
        "last_attempted_at": row.last_attempted_at.map(to_pydantic_isoformat),
        "next_retry_at": row.next_retry_at.map(to_pydantic_isoformat),
    })
}

#[derive(Deserialize)]
struct QueueJobsQuery {
    status: Option<String>,
    domain: Option<String>,
    limit: Option<i64>,
    offset: Option<i64>,
}

/// `Query(50, ge=1, le=200)`/`Query(0, ge=0)`(FastAPI、Python版の
/// `list_queue_jobs`)の範囲検証を移植したもの。
fn validate_queue_jobs_query(
    limit: Option<i64>,
    offset: Option<i64>,
) -> Result<(i64, i64), AppError> {
    let limit = limit.unwrap_or(50);
    if !(1..=200).contains(&limit) {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "limit must be between 1 and 200",
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

/// `domain`クエリパラメータを`app.services.queue_service`の
/// `target_inbox_url.ilike(f"%://{domain}/%")`と同じILIKEパターンへ変換する。
fn domain_ilike_pattern(domain: Option<&str>) -> Option<String> {
    domain.map(|d| format!("%://{d}/%"))
}

/// `app.services.queue_service.get_queue_jobs` を移植したもの。
async fn list_queue_jobs(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Query(params): Query<QueueJobsQuery>,
) -> Result<Response, AppError> {
    require_admin_role(&state, &current_user, &method).await?;
    let (limit, offset) = validate_queue_jobs_query(params.limit, params.offset)?;
    let domain_pattern = domain_ilike_pattern(params.domain.as_deref());

    let rows: Vec<QueueJobRow> = sqlx::query_as(
        "SELECT id, target_inbox_url, status, attempts, max_attempts, error_message, \
                created_at, last_attempted_at, next_retry_at \
         FROM delivery_queue \
         WHERE ($1::text IS NULL OR status = $1) \
           AND ($2::text IS NULL OR target_inbox_url ILIKE $2) \
         ORDER BY created_at DESC \
         LIMIT $3 OFFSET $4",
    )
    .bind(&params.status)
    .bind(&domain_pattern)
    .bind(limit)
    .bind(offset)
    .fetch_all(&state.db)
    .await?;

    let total: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM delivery_queue \
         WHERE ($1::text IS NULL OR status = $1) \
           AND ($2::text IS NULL OR target_inbox_url ILIKE $2)",
    )
    .bind(&params.status)
    .bind(&domain_pattern)
    .fetch_one(&state.db)
    .await?;

    Ok(Json(json!({
        "jobs": rows.iter().map(queue_job_json).collect::<Vec<_>>(),
        "total": total,
    }))
    .into_response())
}

/// `app.services.queue_service.retry_job` を移植したもの。
async fn retry_queue_job(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Path(job_id): Path<Uuid>,
) -> Result<Response, AppError> {
    require_admin_role(&state, &current_user, &method).await?;

    let result = sqlx::query(
        "UPDATE delivery_queue \
         SET status = 'pending', next_retry_at = NULL, attempts = 0, error_message = NULL \
         WHERE id = $1 AND status = 'dead'",
    )
    .bind(job_id)
    .execute(&state.db)
    .await?;

    if result.rows_affected() == 0 {
        return Err(AppError::not_found("Job not found or not dead"));
    }
    Ok(Json(json!({ "ok": true })).into_response())
}

#[derive(Deserialize)]
struct DomainQuery {
    domain: Option<String>,
}

/// `app.services.queue_service.retry_all_dead` を移植したもの。
async fn retry_all_dead_jobs(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Query(params): Query<DomainQuery>,
) -> Result<Response, AppError> {
    require_admin_role(&state, &current_user, &method).await?;
    let domain_pattern = domain_ilike_pattern(params.domain.as_deref());

    let result = sqlx::query(
        "UPDATE delivery_queue \
         SET status = 'pending', next_retry_at = NULL, attempts = 0, error_message = NULL \
         WHERE status = 'dead' AND ($1::text IS NULL OR target_inbox_url ILIKE $1)",
    )
    .bind(&domain_pattern)
    .execute(&state.db)
    .await?;

    Ok(Json(json!({ "ok": true, "retried": result.rows_affected() })).into_response())
}

#[derive(Deserialize)]
struct PurgeQuery {
    older_than_hours: Option<i64>,
}

/// `Query(24, ge=1)`(FastAPI、Python版の`purge_delivered_jobs`)の範囲検証を
/// 移植したもの。
fn validate_older_than_hours(value: Option<i64>) -> Result<i64, AppError> {
    let hours = value.unwrap_or(24);
    if hours < 1 {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "older_than_hours must be greater than or equal to 1",
        ));
    }
    Ok(hours)
}

/// `app.services.queue_service.purge_delivered` を移植したもの。
async fn purge_delivered_jobs(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Query(params): Query<PurgeQuery>,
) -> Result<Response, AppError> {
    require_admin_role(&state, &current_user, &method).await?;
    let hours = validate_older_than_hours(params.older_than_hours)?;

    let cutoff = Utc::now().with_nanosecond(0).unwrap() - chrono::Duration::hours(hours);

    let result =
        sqlx::query("DELETE FROM delivery_queue WHERE status = 'delivered' AND created_at < $1")
            .bind(cutoff)
            .execute(&state.db)
            .await?;

    Ok(Json(json!({ "ok": true, "purged": result.rows_affected() })).into_response())
}

#[derive(sqlx::FromRow)]
struct PendingRegistrationRow {
    id: Uuid,
    username: String,
    email: String,
    reason: Option<String>,
    created_at: DateTime<Utc>,
}

/// `app.schemas.admin.PendingRegistrationResponse` を移植したもの。
fn pending_registration_json(row: &PendingRegistrationRow) -> Value {
    json!({
        "id": row.id,
        "username": row.username,
        "email": row.email,
        "reason": row.reason,
        "created_at": to_pydantic_isoformat(row.created_at),
    })
}

/// `app.api.admin.list_pending_registrations` を移植したもの。
async fn list_pending_registrations(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
) -> Result<Response, AppError> {
    require_permission(&state, &current_user, &method, "registrations").await?;

    let rows: Vec<PendingRegistrationRow> = sqlx::query_as(
        "SELECT u.id, a.username, u.email, u.registration_reason AS reason, u.created_at \
         FROM users u \
         JOIN actors a ON a.id = u.actor_id \
         WHERE u.approval_status = 'pending' \
         ORDER BY u.created_at ASC",
    )
    .fetch_all(&state.db)
    .await?;

    Ok(Json(
        rows.iter()
            .map(pending_registration_json)
            .collect::<Vec<_>>(),
    )
    .into_response())
}

#[derive(sqlx::FromRow)]
struct PendingUserRow {
    id: Uuid,
    actor_id: Uuid,
    approval_status: String,
}

async fn fetch_pending_user(
    db: &sqlx::PgPool,
    user_id: Uuid,
) -> Result<Option<PendingUserRow>, AppError> {
    let row = sqlx::query_as("SELECT id, actor_id, approval_status FROM users WHERE id = $1")
        .bind(user_id)
        .fetch_optional(db)
        .await?;
    Ok(row)
}

/// `app.api.admin.approve_registration` を移植したもの。
async fn approve_registration(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Path(user_id): Path<Uuid>,
) -> Result<Response, AppError> {
    require_permission(&state, &current_user, &method, "registrations").await?;

    let target = fetch_pending_user(&state.db, user_id)
        .await?
        .ok_or_else(|| AppError::not_found("User not found"))?;
    if target.approval_status != "pending" {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "User is not pending approval",
        ));
    }

    sqlx::query("UPDATE users SET approval_status = 'approved' WHERE id = $1")
        .bind(user_id)
        .execute(&state.db)
        .await?;

    log_action(
        &state,
        current_user.id,
        "approve_registration",
        "user",
        &target.id.to_string(),
        None,
    )
    .await?;

    Ok(Json(json!({ "ok": true })).into_response())
}

/// `app.api.admin.reject_registration` を移植したもの。ログ記録の後、
/// ユーザー本体と紐づくactorを削除する(Python版の`db.delete(target)` →
/// `db.delete(actor)`と同じ順序)。
async fn reject_registration(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Path(user_id): Path<Uuid>,
) -> Result<Response, AppError> {
    require_permission(&state, &current_user, &method, "registrations").await?;

    let target = fetch_pending_user(&state.db, user_id)
        .await?
        .ok_or_else(|| AppError::not_found("User not found"))?;
    if target.approval_status != "pending" {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "User is not pending approval",
        ));
    }

    log_action(
        &state,
        current_user.id,
        "reject_registration",
        "user",
        &target.id.to_string(),
        None,
    )
    .await?;

    sqlx::query("DELETE FROM users WHERE id = $1")
        .bind(target.id)
        .execute(&state.db)
        .await?;
    sqlx::query("DELETE FROM actors WHERE id = $1")
        .bind(target.actor_id)
        .execute(&state.db)
        .await?;

    Ok(Json(json!({ "ok": true })).into_response())
}

// ── 連合サーバー一覧/詳細 (`app.services.federation_service`) ──────────

/// リモートサーバーの集計を行うCTE群。`domain`ごとに1行(`actor_agg`)を
/// 基準に`note_agg`/`delivery_agg`/`domain_blocks`をLEFT JOINするため、
/// 追加のJOINで行が増減することはない(いずれも`domain`単位でGROUP BY済み、
/// `domain_blocks.domain`はUNIQUE制約)。ステータスフィルタは
/// `$1::text`(`effective_status`、`None`なら無条件)で一覧・件数の両方から
/// 共有する。
const FEDERATION_AGG_CTE: &str = "
    WITH actor_agg AS (
        SELECT domain,
               COUNT(id) AS user_count,
               MAX(last_fetched_at) AS last_activity_at,
               MIN(created_at) AS first_seen_at
        FROM actors
        WHERE domain IS NOT NULL
          AND ($2::text IS NULL OR domain ILIKE $2)
        GROUP BY domain
    ),
    note_agg AS (
        SELECT a.domain AS domain, COUNT(n.id) AS note_count
        FROM notes n
        JOIN actors a ON a.id = n.actor_id
        WHERE a.domain IS NOT NULL AND n.deleted_at IS NULL
        GROUP BY a.domain
    ),
    delivery_agg AS (
        SELECT substring(target_inbox_url from 'https?://([^/]+)') AS domain,
               COUNT(*) FILTER (WHERE status = 'delivered') AS d_success,
               COUNT(*) FILTER (WHERE status IN ('failed', 'processing')) AS d_failure,
               COUNT(*) FILTER (WHERE status = 'pending') AS d_pending,
               COUNT(*) FILTER (WHERE status = 'dead') AS d_dead
        FROM delivery_queue
        GROUP BY substring(target_inbox_url from 'https?://([^/]+)')
    )
    SELECT actor_agg.domain,
           actor_agg.user_count,
           actor_agg.last_activity_at,
           actor_agg.first_seen_at,
           COALESCE(note_agg.note_count, 0) AS note_count,
           COALESCE(delivery_agg.d_success, 0) AS d_success,
           COALESCE(delivery_agg.d_failure, 0) AS d_failure,
           COALESCE(delivery_agg.d_pending, 0) AS d_pending,
           COALESCE(delivery_agg.d_dead, 0) AS d_dead,
           domain_blocks.severity AS block_severity
    FROM actor_agg
    LEFT JOIN note_agg ON actor_agg.domain = note_agg.domain
    LEFT JOIN delivery_agg ON actor_agg.domain = delivery_agg.domain
    LEFT JOIN domain_blocks ON actor_agg.domain = domain_blocks.domain
    WHERE ($1::text IS NULL)
       OR ($1 = 'active' AND domain_blocks.domain IS NULL)
       OR ($1 = 'suspended' AND domain_blocks.severity = 'suspend')
       OR ($1 = 'silenced' AND domain_blocks.severity = 'silence')
";

#[derive(sqlx::FromRow)]
struct FederatedServerRow {
    domain: String,
    user_count: i64,
    last_activity_at: Option<DateTime<Utc>>,
    first_seen_at: Option<DateTime<Utc>>,
    note_count: i64,
    d_success: i64,
    d_failure: i64,
    d_pending: i64,
    d_dead: i64,
    block_severity: Option<String>,
}

/// `app.services.federation_service`の`block_severity`→`status`変換を
/// 移植したもの。
fn federation_status(block_severity: Option<&str>) -> &'static str {
    match block_severity {
        Some("suspend") => "suspended",
        Some("silence") => "silenced",
        _ => "active",
    }
}

/// `app.schemas.admin.FederatedServerResponse`を移植したもの。
fn federated_server_json(row: &FederatedServerRow) -> Value {
    json!({
        "domain": row.domain,
        "user_count": row.user_count,
        "note_count": row.note_count,
        "last_activity_at": row.last_activity_at.map(to_pydantic_isoformat),
        "first_seen_at": row.first_seen_at.map(to_pydantic_isoformat),
        "status": federation_status(row.block_severity.as_deref()),
        "block_severity": row.block_severity,
        "delivery_stats": {
            "success": row.d_success,
            "failure": row.d_failure,
            "pending": row.d_pending,
            "dead": row.d_dead,
        },
    })
}

#[derive(Deserialize)]
struct FederationQuery {
    limit: Option<i64>,
    offset: Option<i64>,
    sort: Option<String>,
    order: Option<String>,
    search: Option<String>,
    status: Option<String>,
}

struct ValidatedFederationQuery {
    limit: i64,
    offset: i64,
    sort_col: &'static str,
    ascending: bool,
    search_pattern: Option<String>,
    status: Option<&'static str>,
}

/// `Query(default=40, le=200, ge=1)`/`Query(default=0, ge=0)`/
/// `search: Query(max_length=255)`(FastAPI、Python版の`list_federated_servers`)
/// の範囲検証を移植したもの。
fn validate_federation_query(
    params: &FederationQuery,
) -> Result<ValidatedFederationQuery, AppError> {
    let limit = params.limit.unwrap_or(40);
    if !(1..=200).contains(&limit) {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "limit must be between 1 and 200",
        ));
    }
    let offset = params.offset.unwrap_or(0);
    if offset < 0 {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "offset must be greater than or equal to 0",
        ));
    }

    let sort = match params.sort.as_deref().unwrap_or("user_count") {
        "domain" => "domain",
        "user_count" => "user_count",
        "note_count" => "note_count",
        "last_activity" => "last_activity",
        _ => {
            return Err(AppError::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "sort must be one of: domain, user_count, note_count, last_activity",
            ))
        }
    };
    let ascending = match params.order.as_deref().unwrap_or("desc") {
        "asc" => true,
        "desc" => false,
        _ => {
            return Err(AppError::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "order must be one of: asc, desc",
            ))
        }
    };

    if let Some(search) = &params.search {
        if search.chars().count() > 255 {
            return Err(AppError::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "search must be at most 255 characters",
            ));
        }
    }
    let search_pattern = params.search.as_ref().map(|s| {
        let escaped = s.replace('%', "\\%").replace('_', "\\_");
        format!("%{escaped}%")
    });

    let status = match params.status.as_deref() {
        None | Some("all") => None,
        Some("active") => Some("active"),
        Some("suspended") => Some("suspended"),
        Some("silenced") => Some("silenced"),
        _ => {
            return Err(AppError::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "status must be one of: all, active, suspended, silenced",
            ))
        }
    };

    Ok(ValidatedFederationQuery {
        limit,
        offset,
        sort_col: sort,
        ascending,
        search_pattern,
        status,
    })
}

/// `app.services.federation_service.get_federated_servers` を移植したもの。
async fn list_federated_servers(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Query(params): Query<FederationQuery>,
) -> Result<Response, AppError> {
    require_permission(&state, &current_user, &method, "federation").await?;
    let ValidatedFederationQuery {
        limit,
        offset,
        sort_col: sort,
        ascending,
        search_pattern,
        status,
    } = validate_federation_query(&params)?;

    let total: i64 = sqlx::query_scalar(&format!("SELECT COUNT(*) FROM ({FEDERATION_AGG_CTE}) t"))
        .bind(status)
        .bind(&search_pattern)
        .fetch_one(&state.db)
        .await?;

    let sort_col = match sort {
        "domain" => "domain",
        "user_count" => "user_count",
        "note_count" => "note_count",
        _ => "last_activity_at",
    };
    let order_clause = if ascending {
        format!("{sort_col} ASC NULLS LAST")
    } else {
        format!("{sort_col} DESC NULLS FIRST")
    };

    let rows: Vec<FederatedServerRow> = sqlx::query_as(&format!(
        "{FEDERATION_AGG_CTE} ORDER BY {order_clause} LIMIT $3 OFFSET $4"
    ))
    .bind(status)
    .bind(&search_pattern)
    .bind(limit)
    .bind(offset)
    .fetch_all(&state.db)
    .await?;

    Ok(Json(json!({
        "servers": rows.iter().map(federated_server_json).collect::<Vec<_>>(),
        "total": total,
    }))
    .into_response())
}

#[derive(sqlx::FromRow)]
struct FederationActorAggRow {
    user_count: i64,
    last_activity_at: Option<DateTime<Utc>>,
    first_seen_at: Option<DateTime<Utc>>,
}

#[derive(sqlx::FromRow)]
struct FederationDeliveryAggRow {
    d_success: i64,
    d_failure: i64,
    d_pending: i64,
    d_dead: i64,
}

#[derive(sqlx::FromRow)]
struct DomainBlockInfoRow {
    severity: String,
    reason: Option<String>,
}

#[derive(sqlx::FromRow)]
struct ActorSummaryRow {
    username: String,
    display_name: Option<String>,
    ap_id: String,
    last_fetched_at: Option<DateTime<Utc>>,
}

fn actor_summary_json(row: &ActorSummaryRow) -> Value {
    json!({
        "username": row.username,
        "display_name": row.display_name,
        "ap_id": row.ap_id,
        "last_fetched_at": row.last_fetched_at.map(to_pydantic_isoformat),
    })
}

/// `app.services.federation_service.get_federated_server_detail` を移植したもの。
async fn get_federated_server_detail_endpoint(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Path(domain): Path<String>,
) -> Result<Response, AppError> {
    require_permission(&state, &current_user, &method, "federation").await?;

    // GROUP BY無しの集計クエリは対象0件でも必ず1行返る(COUNTは0)ため、
    // Python版の`agg.user_count == 0`と同じ条件で404にする。
    let agg: FederationActorAggRow = sqlx::query_as(
        "SELECT COUNT(id) AS user_count, \
                MAX(last_fetched_at) AS last_activity_at, \
                MIN(created_at) AS first_seen_at \
         FROM actors WHERE domain = $1",
    )
    .bind(&domain)
    .fetch_one(&state.db)
    .await?;
    if agg.user_count == 0 {
        return Err(AppError::not_found("Server not found"));
    }

    let note_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(n.id) FROM notes n \
         JOIN actors a ON a.id = n.actor_id \
         WHERE a.domain = $1 AND n.deleted_at IS NULL",
    )
    .bind(&domain)
    .fetch_one(&state.db)
    .await?;

    let delivery: FederationDeliveryAggRow = sqlx::query_as(
        "SELECT COUNT(*) FILTER (WHERE status = 'delivered') AS d_success, \
                COUNT(*) FILTER (WHERE status IN ('failed', 'processing')) AS d_failure, \
                COUNT(*) FILTER (WHERE status = 'pending') AS d_pending, \
                COUNT(*) FILTER (WHERE status = 'dead') AS d_dead \
         FROM delivery_queue \
         WHERE substring(target_inbox_url from 'https?://([^/]+)') = $1",
    )
    .bind(&domain)
    .fetch_one(&state.db)
    .await?;

    let block: Option<DomainBlockInfoRow> =
        sqlx::query_as("SELECT severity, reason FROM domain_blocks WHERE domain = $1")
            .bind(&domain)
            .fetch_optional(&state.db)
            .await?;

    let actors: Vec<ActorSummaryRow> = sqlx::query_as(
        "SELECT username, display_name, ap_id, last_fetched_at \
         FROM actors WHERE domain = $1 \
         ORDER BY last_fetched_at DESC NULLS LAST LIMIT 10",
    )
    .bind(&domain)
    .fetch_all(&state.db)
    .await?;

    let block_severity = block.as_ref().map(|b| b.severity.as_str());

    Ok(Json(json!({
        "domain": domain,
        "user_count": agg.user_count,
        "note_count": note_count,
        "last_activity_at": agg.last_activity_at.map(to_pydantic_isoformat),
        "first_seen_at": agg.first_seen_at.map(to_pydantic_isoformat),
        "status": federation_status(block_severity),
        "block_severity": block_severity,
        "block_reason": block.as_ref().and_then(|b| b.reason.as_deref()),
        "delivery_stats": {
            "success": delivery.d_success,
            "failure": delivery.d_failure,
            "pending": delivery.d_pending,
            "dead": delivery.d_dead,
        },
        "recent_actors": actors.iter().map(actor_summary_json).collect::<Vec<_>>(),
    }))
    .into_response())
}

// --- サーバー設定 ---

/// `app.api.admin.get_server_settings`/`update_server_settings`が返す
/// `ServerSettingsResponse`を組み立てる。`settings.get(key, default)`という
/// Pythonのdict.get 2引数版の挙動(defaultはキーが「存在しない」場合のみ
/// 適用され、キーが存在して値がNULL/Noneの場合は適用されない)を
/// フィールドごとに再現する。
fn build_settings_response(settings: &HashMap<String, Option<String>>, config: &Config) -> Value {
    let get_flat = |key: &str| -> Option<String> { settings.get(key).cloned().flatten() };
    let get_with_default = |key: &str, default: &str| -> Option<String> {
        match settings.get(key) {
            Some(v) => v.clone(),
            None => Some(default.to_string()),
        }
    };

    let mode = get_flat("registration_mode").unwrap_or_else(|| {
        let reg_open = get_with_default("registration_open", "true").as_deref() == Some("true");
        (if reg_open { "open" } else { "closed" }).to_string()
    });
    let invite_create_role =
        get_with_default("invite_create_role", "admin").unwrap_or_else(|| "admin".to_string());
    let push_enabled = get_with_default("push_enabled", "true").as_deref() == Some("true");
    let katex_enabled = get_with_default("katex_enabled", "false").as_deref() == Some("true");
    let timeline_default_limit = get_with_default("timeline_default_limit", "20")
        .and_then(|s| s.parse::<i64>().ok())
        .unwrap_or(20);
    let timeline_max_limit = get_with_default("timeline_max_limit", "40")
        .and_then(|s| s.parse::<i64>().ok())
        .unwrap_or(40);
    let vapid_public_key =
        vapid_public_key_base64url(config, get_flat("vapid_private_key").as_deref());

    json!({
        "server_name": get_flat("server_name"),
        "server_description": get_flat("server_description"),
        "tos_url": get_flat("tos_url"),
        "terms_of_service": get_flat("terms_of_service"),
        "privacy_policy": get_flat("privacy_policy"),
        "registration_open": mode != "closed",
        "registration_mode": mode,
        "invite_create_role": invite_create_role,
        "server_icon_url": get_flat("server_icon_url"),
        "server_theme_color": get_flat("server_theme_color"),
        "push_enabled": push_enabled,
        "vapid_public_key": vapid_public_key,
        "timeline_default_limit": timeline_default_limit,
        "timeline_max_limit": timeline_max_limit,
        "katex_enabled": katex_enabled,
    })
}

/// `app.api.admin.get_server_settings` を移植したもの。
async fn get_server_settings(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
) -> Result<Response, AppError> {
    require_admin_role(&state, &current_user, &method).await?;
    let settings = get_all_settings(&state.db).await?;
    Ok(Json(build_settings_response(&settings, &state.config)).into_response())
}

/// `app.schemas.admin.ServerSettingsUpdate`の各フィールドを`exclude_unset=True`
/// 相当(リクエストJSONにキーが存在する場合のみ`Some`)でパースした結果。
/// 検証は全フィールド分をハンドラー本体の実処理より先に完了させる
/// (FastAPI/pydanticがハンドラー呼び出し前にボディ全体を検証するのと同じ、
/// 一部だけ適用された中途半端な更新を防ぐ)。
#[derive(Default)]
struct ParsedSettingsUpdate {
    server_name: Option<Option<String>>,
    server_description: Option<Option<String>>,
    tos_url: Option<Option<String>>,
    terms_of_service: Option<Option<String>>,
    privacy_policy: Option<Option<String>>,
    registration_open: Option<bool>,
    registration_mode: Option<String>,
    invite_create_role: Option<String>,
    server_theme_color: Option<Option<String>>,
    push_enabled: Option<bool>,
    timeline_default_limit: Option<i64>,
    timeline_max_limit: Option<i64>,
    katex_enabled: Option<bool>,
}

fn get_nullable_string(
    map: &Map<String, Value>,
    key: &str,
    max_len: usize,
) -> Result<Option<Option<String>>, AppError> {
    let Some(value) = map.get(key) else {
        return Ok(None);
    };
    match value {
        Value::Null => Ok(Some(None)),
        Value::String(s) => {
            if s.chars().count() > max_len {
                return Err(AppError::new(
                    StatusCode::UNPROCESSABLE_ENTITY,
                    format!("{key} must be at most {max_len} characters"),
                ));
            }
            Ok(Some(Some(s.clone())))
        }
        _ => Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            format!("{key} must be a string or null"),
        )),
    }
}

/// bool|Noneフィールド。Pythonの`"true" if value else "false"`という
/// truthy/falsy評価に合わせ、明示的な`null`は`false`として扱う。
fn get_optional_bool(map: &Map<String, Value>, key: &str) -> Result<Option<bool>, AppError> {
    let Some(value) = map.get(key) else {
        return Ok(None);
    };
    match value {
        Value::Null => Ok(Some(false)),
        Value::Bool(b) => Ok(Some(*b)),
        _ => Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            format!("{key} must be a boolean"),
        )),
    }
}

/// `registration_mode`/`invite_create_role`の`Field(None, pattern=...)`を
/// 移植したもの。Python版はNoneに対してはpatternを適用せず後続処理で
/// 未定義動作(前者はDB値をNULL化した上で承認待ちユーザーを一括却下、
/// 後者は`ServerSettingsResponse`構築時にpydantic検証エラーで500)になるが、
/// 実運用のUIから到達しない経路のため、backend-rsでは明示的な`null`は
/// 422として拒否する(意図的な簡略化)。
fn get_enum_string(
    map: &Map<String, Value>,
    key: &str,
    allowed: &[&str],
) -> Result<Option<String>, AppError> {
    let Some(value) = map.get(key) else {
        return Ok(None);
    };
    match value {
        Value::String(s) if allowed.iter().any(|a| a == s) => Ok(Some(s.clone())),
        _ => Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            format!("{key} must be one of {allowed:?}"),
        )),
    }
}

/// `Field(None, ge=1, le=1000)`を移植したもの。明示的な`null`はPython版だと
/// `int(None)`で500になるため(`get_enum_string`と同じ理由で)422として拒否する。
fn get_bounded_int(
    map: &Map<String, Value>,
    key: &str,
    min: i64,
    max: i64,
) -> Result<Option<i64>, AppError> {
    let Some(value) = map.get(key) else {
        return Ok(None);
    };
    match value.as_i64() {
        Some(n) if (min..=max).contains(&n) => Ok(Some(n)),
        _ => Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            format!("{key} must be between {min} and {max}"),
        )),
    }
}

fn is_valid_theme_color(s: &str) -> bool {
    let bytes = s.as_bytes();
    bytes.len() == 7 && bytes[0] == b'#' && bytes[1..].iter().all(u8::is_ascii_hexdigit)
}

fn parse_settings_update(map: &Map<String, Value>) -> Result<ParsedSettingsUpdate, AppError> {
    let server_theme_color = match get_nullable_string(map, "server_theme_color", 7)? {
        Some(Some(s)) if !is_valid_theme_color(&s) => {
            return Err(AppError::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "server_theme_color must match ^#[0-9a-fA-F]{6}$",
            ))
        }
        other => other,
    };

    Ok(ParsedSettingsUpdate {
        server_name: get_nullable_string(map, "server_name", 255)?,
        server_description: get_nullable_string(map, "server_description", 2000)?,
        tos_url: get_nullable_string(map, "tos_url", 2048)?,
        terms_of_service: get_nullable_string(map, "terms_of_service", 50000)?,
        privacy_policy: get_nullable_string(map, "privacy_policy", 50000)?,
        registration_open: get_optional_bool(map, "registration_open")?,
        registration_mode: get_enum_string(
            map,
            "registration_mode",
            &["open", "invite", "closed", "approval"],
        )?,
        invite_create_role: get_enum_string(
            map,
            "invite_create_role",
            &["admin", "moderator", "user"],
        )?,
        server_theme_color,
        push_enabled: get_optional_bool(map, "push_enabled")?,
        timeline_default_limit: get_bounded_int(map, "timeline_default_limit", 1, 1000)?,
        timeline_max_limit: get_bounded_int(map, "timeline_max_limit", 1, 1000)?,
        katex_enabled: get_optional_bool(map, "katex_enabled")?,
    })
}

fn bool_str(flag: bool) -> &'static str {
    if flag {
        "true"
    } else {
        "false"
    }
}

/// `app.api.admin._resolve_pending_users` を移植したもの。承認制モードから
/// 離脱する際、承認待ちユーザーを一括処理する: `open`への変更は全員承認、
/// それ以外(`closed`/`invite`)は全員却下(ユーザー+actor削除、
/// `reject_registration`(#1169)と同じ削除パターン)。
async fn resolve_pending_users(
    state: &AppState,
    moderator_id: Uuid,
    new_mode: &str,
) -> Result<(), AppError> {
    let pending: Vec<PendingUserRow> = sqlx::query_as(
        "SELECT id, actor_id, approval_status FROM users WHERE approval_status = 'pending'",
    )
    .fetch_all(&state.db)
    .await?;

    for user in pending {
        if new_mode == "open" {
            sqlx::query("UPDATE users SET approval_status = 'approved' WHERE id = $1")
                .bind(user.id)
                .execute(&state.db)
                .await?;
            log_action(
                state,
                moderator_id,
                "approve_registration",
                "user",
                &user.id.to_string(),
                None,
            )
            .await?;
        } else {
            log_action(
                state,
                moderator_id,
                "reject_registration",
                "user",
                &user.id.to_string(),
                None,
            )
            .await?;
            sqlx::query("DELETE FROM users WHERE id = $1")
                .bind(user.id)
                .execute(&state.db)
                .await?;
            sqlx::query("DELETE FROM actors WHERE id = $1")
                .bind(user.actor_id)
                .execute(&state.db)
                .await?;
        }
    }
    Ok(())
}

/// `app.api.admin.update_server_settings`の更新ループ本体を移植したもの
/// (pydanticのフィールド宣言順 = `model_dump(exclude_unset=True)`の
/// 反復順と同じ順序で適用する)。
async fn apply_settings_update(
    state: &AppState,
    moderator_id: Uuid,
    parsed: ParsedSettingsUpdate,
) -> Result<(), AppError> {
    if let Some(v) = &parsed.server_name {
        set_setting(&state.db, &state.redis, "server_name", v.as_deref()).await?;
    }
    if let Some(v) = &parsed.server_description {
        set_setting(&state.db, &state.redis, "server_description", v.as_deref()).await?;
    }
    if let Some(v) = &parsed.tos_url {
        set_setting(&state.db, &state.redis, "tos_url", v.as_deref()).await?;
    }
    if let Some(v) = &parsed.terms_of_service {
        set_setting(&state.db, &state.redis, "terms_of_service", v.as_deref()).await?;
    }
    if let Some(v) = &parsed.privacy_policy {
        set_setting(&state.db, &state.redis, "privacy_policy", v.as_deref()).await?;
    }
    if let Some(flag) = parsed.registration_open {
        set_setting(
            &state.db,
            &state.redis,
            "registration_open",
            Some(bool_str(flag)),
        )
        .await?;
    }
    if let Some(mode) = &parsed.registration_mode {
        set_setting(
            &state.db,
            &state.redis,
            "registration_mode",
            Some(mode.as_str()),
        )
        .await?;
        set_setting(
            &state.db,
            &state.redis,
            "registration_open",
            Some(bool_str(mode != "closed")),
        )
        .await?;
        if mode != "approval" {
            resolve_pending_users(state, moderator_id, mode).await?;
        }
    }
    if let Some(role) = &parsed.invite_create_role {
        set_setting(
            &state.db,
            &state.redis,
            "invite_create_role",
            Some(role.as_str()),
        )
        .await?;
    }
    if let Some(v) = &parsed.server_theme_color {
        set_setting(&state.db, &state.redis, "server_theme_color", v.as_deref()).await?;
    }
    if let Some(flag) = parsed.push_enabled {
        set_setting(
            &state.db,
            &state.redis,
            "push_enabled",
            Some(bool_str(flag)),
        )
        .await?;
    }
    if let Some(n) = parsed.timeline_default_limit {
        set_setting(
            &state.db,
            &state.redis,
            "timeline_default_limit",
            Some(n.to_string().as_str()),
        )
        .await?;
    }
    if let Some(n) = parsed.timeline_max_limit {
        set_setting(
            &state.db,
            &state.redis,
            "timeline_max_limit",
            Some(n.to_string().as_str()),
        )
        .await?;
    }
    if let Some(flag) = parsed.katex_enabled {
        set_setting(
            &state.db,
            &state.redis,
            "katex_enabled",
            Some(bool_str(flag)),
        )
        .await?;
    }
    Ok(())
}

/// `app.api.admin.update_server_settings` を移植したもの。
async fn update_server_settings(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
    Json(body): Json<Map<String, Value>>,
) -> Result<Response, AppError> {
    require_admin_role(&state, &current_user, &method).await?;
    let parsed = parse_settings_update(&body)?;
    apply_settings_update(&state, current_user.id, parsed).await?;

    log_action(
        &state,
        current_user.id,
        "update_settings",
        "server",
        "settings",
        None,
    )
    .await?;

    // instance_infoキャッシュを無効化 (設定変更を即時反映、失敗してもベストエフォート)
    let mut conn = state.redis.clone();
    let _: Result<(), redis::RedisError> = conn.del("perf:instance_info_v1").await;
    let _: Result<(), redis::RedisError> = conn.del("perf:instance_info_v2").await;

    let settings = get_all_settings(&state.db).await?;
    Ok(Json(build_settings_response(&settings, &state.config)).into_response())
}

// --- 統計 ---

/// `app.api.admin.get_admin_stats` を移植したもの。
async fn get_admin_stats(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
) -> Result<Response, AppError> {
    require_permission(&state, &current_user, &method, "users").await?;

    let user_count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM users")
        .fetch_one(&state.db)
        .await?;

    let note_count: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM notes WHERE deleted_at IS NULL AND local = true")
            .fetch_one(&state.db)
            .await?;

    let domain_count: i64 = sqlx::query_scalar(
        r#"
        SELECT COUNT(DISTINCT domain) FROM (
            SELECT substring(target_inbox_url from 'https?://([^/]+)') AS domain
            FROM delivery_queue
            WHERE status IN ('delivered', 'pending', 'processing')
            UNION
            SELECT a.domain AS domain
            FROM followers f
            JOIN actors a ON a.id = f.following_id
            WHERE f.follower_id IN (SELECT id FROM actors WHERE domain IS NULL)
              AND a.domain IS NOT NULL
            UNION
            SELECT a.domain AS domain
            FROM followers f
            JOIN actors a ON a.id = f.follower_id
            WHERE f.following_id IN (SELECT id FROM actors WHERE domain IS NULL)
              AND a.domain IS NOT NULL
        ) AS active_domains
        "#,
    )
    .fetch_one(&state.db)
    .await?;

    Ok(Json(json!({
        "user_count": user_count,
        "note_count": note_count,
        "domain_count": domain_count,
    }))
    .into_response())
}

/// `app.api.admin.get_system_stats` の `/proc` 読み取り部分を移植したもの。
/// Python版と同じく各読み取りはベストエフォート(失敗してもデフォルト値
/// のまま処理を続ける)。
fn read_loadavg() -> Option<(f64, f64, f64)> {
    let content = std::fs::read_to_string("/proc/loadavg").ok()?;
    let mut parts = content.split_whitespace();
    let one = parts.next()?.parse().ok()?;
    let five = parts.next()?.parse().ok()?;
    let fifteen = parts.next()?.parse().ok()?;
    Some((one, five, fifteen))
}

struct MemInfo {
    total_mb: i64,
    available_mb: i64,
    percent: f64,
}

fn read_meminfo() -> Option<MemInfo> {
    let content = std::fs::read_to_string("/proc/meminfo").ok()?;
    let mut total_kb: Option<i64> = None;
    let mut available_kb: Option<i64> = None;
    for line in content.lines() {
        let mut parts = line.splitn(2, ':');
        let key = parts.next()?.trim();
        let rest = parts.next();
        if key == "MemTotal" || key == "MemAvailable" {
            let value = rest?.split_whitespace().next()?.parse::<i64>().ok()?;
            if key == "MemTotal" {
                total_kb = Some(value);
            } else {
                available_kb = Some(value);
            }
        }
    }
    let total_kb = total_kb?;
    let available_kb = available_kb?;
    let percent = if total_kb > 0 {
        (1.0 - available_kb as f64 / total_kb as f64) * 100.0
    } else {
        0.0
    };
    Some(MemInfo {
        total_mb: total_kb / 1024,
        available_mb: available_kb / 1024,
        percent: (percent * 10.0).round() / 10.0,
    })
}

fn read_uptime_seconds() -> Option<f64> {
    let content = std::fs::read_to_string("/proc/uptime").ok()?;
    content.split_whitespace().next()?.parse().ok()
}

/// `app.api.admin.get_system_stats` を移植したもの。
async fn get_system_stats(
    State(state): State<AppState>,
    method: Method,
    current_user: CurrentUser,
) -> Result<Response, AppError> {
    require_admin_role(&state, &current_user, &method).await?;

    let db_pool_size = state.db.size();
    let db_pool_checked_in = state.db.num_idle() as u32;
    let db_pool_checked_out = db_pool_size.saturating_sub(db_pool_checked_in);

    let mut conn = state.redis.clone();
    let info_text: String = redis::cmd("INFO")
        .query_async(&mut conn)
        .await
        .unwrap_or_default();
    let mut valkey_connected_clients: i64 = 0;
    let mut valkey_used_memory_human = String::new();
    let mut valkey_total_keys: i64 = 0;
    for line in info_text.lines() {
        let Some((key, value)) = line.split_once(':') else {
            continue;
        };
        if key == "connected_clients" {
            valkey_connected_clients = value.trim().parse().unwrap_or(0);
        } else if key == "used_memory_human" {
            valkey_used_memory_human = value.trim().to_string();
        } else if key.starts_with("db") {
            for field in value.split(',') {
                if let Some(count) = field.strip_prefix("keys=") {
                    valkey_total_keys += count.trim().parse::<i64>().unwrap_or(0);
                }
            }
        }
    }

    let (load_avg_1m, load_avg_5m, load_avg_15m) = read_loadavg().unwrap_or((0.0, 0.0, 0.0));
    let mem = read_meminfo();
    let uptime_seconds = read_uptime_seconds().unwrap_or(0.0);

    let heartbeat: Option<String> = conn.get("worker:heartbeat").await.unwrap_or(None);
    let worker_alive = heartbeat.is_some();

    Ok(Json(json!({
        "db_pool_size": db_pool_size,
        "db_pool_checked_in": db_pool_checked_in,
        "db_pool_checked_out": db_pool_checked_out,
        "db_pool_overflow": 0,
        "valkey_connected_clients": valkey_connected_clients,
        "valkey_used_memory_human": valkey_used_memory_human,
        "valkey_total_keys": valkey_total_keys,
        "load_avg_1m": load_avg_1m,
        "load_avg_5m": load_avg_5m,
        "load_avg_15m": load_avg_15m,
        "memory_total_mb": mem.as_ref().map(|m| m.total_mb).unwrap_or(0),
        "memory_available_mb": mem.as_ref().map(|m| m.available_mb).unwrap_or(0),
        "memory_percent": mem.as_ref().map(|m| m.percent).unwrap_or(0.0),
        "uptime_seconds": uptime_seconds,
        "worker_alive": worker_alive,
        "worker_last_heartbeat": heartbeat,
    }))
    .into_response())
}
