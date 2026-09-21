//! `app/api/mastodon/statuses.py` のうち、Stage 3 でRust化するブックマーク
//! 書き込みパス (`bookmark`/`unbookmark`) のみを切り出したもの。
//! 投稿本体のCRUD・リアクション・リノート等の巨大な残りの面は Stage 4 以降。

use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::post;
use axum::{Json, Router};
use serde_json::json;
use uuid::Uuid;

use crate::activitypub::{render_add_activity, render_remove_activity};
use crate::auth::CurrentUser;
use crate::db;
use crate::delivery::enqueue_delivery;
use crate::error::AppError;
use crate::follows::get_follower_inboxes;
use crate::note_visibility::{check_note_visible, fetch_note_for_visibility};
use crate::state::AppState;

/// `app.services.pinned_note_service.MAX_PINS` と同一。
const MAX_PINS: i64 = 5;

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/api/v1/statuses/:note_id/bookmark", post(bookmark_status))
        .route(
            "/api/v1/statuses/:note_id/unbookmark",
            post(unbookmark_status),
        )
        .route("/api/v1/statuses/:note_id/pin", post(pin_status))
        .route("/api/v1/statuses/:note_id/unpin", post(unpin_status))
}

/// `app/api/mastodon/statuses.py` の `bookmark_status` を移植したもの。
async fn bookmark_status(
    State(state): State<AppState>,
    current_user: CurrentUser,
    Path(note_id): Path<Uuid>,
) -> Result<Response, AppError> {
    current_user.require_scope("write:bookmarks")?;

    let note = fetch_note_for_visibility(&state.db, note_id)
        .await?
        .ok_or_else(|| AppError::not_found("Note not found"))?;
    if !check_note_visible(&state.db, &note, current_user.actor_id).await? {
        return Err(AppError::not_found("Note not found"));
    }

    let result = sqlx::query(
        "INSERT INTO bookmarks (id, actor_id, note_id, created_at) VALUES ($1, $2, $3, $4)",
    )
    .bind(db::new_id())
    .bind(current_user.actor_id)
    .bind(note_id)
    .bind(db::now())
    .execute(&state.db)
    .await;

    match result {
        Ok(_) => {}
        Err(sqlx::Error::Database(db_err)) if db_err.code().as_deref() == Some("23505") => {
            return Err(AppError::new(
                axum::http::StatusCode::UNPROCESSABLE_ENTITY,
                "Already bookmarked",
            ));
        }
        Err(e) => return Err(e.into()),
    }

    Ok(Json(json!({ "ok": true })).into_response())
}

/// `app/api/mastodon/statuses.py` の `unbookmark_status` を移植したもの。
/// (削除は自分のブックマークを外すだけの操作のため、bookmarkと異なり
/// ノートの現在の可視性チェックは行わない — Python版と同じ)
async fn unbookmark_status(
    State(state): State<AppState>,
    current_user: CurrentUser,
    Path(note_id): Path<Uuid>,
) -> Result<Response, AppError> {
    current_user.require_scope("write:bookmarks")?;

    fetch_note_for_visibility(&state.db, note_id)
        .await?
        .ok_or_else(|| AppError::not_found("Note not found"))?;

    let result = sqlx::query("DELETE FROM bookmarks WHERE actor_id = $1 AND note_id = $2")
        .bind(current_user.actor_id)
        .bind(note_id)
        .execute(&state.db)
        .await?;

    if result.rows_affected() == 0 {
        return Err(AppError::new(
            axum::http::StatusCode::UNPROCESSABLE_ENTITY,
            "Not bookmarked",
        ));
    }

    Ok(Json(json!({ "ok": true })).into_response())
}

#[derive(sqlx::FromRow)]
struct PinNoteRow {
    actor_id: Uuid,
    visibility: String,
    renote_of_id: Option<Uuid>,
    ap_id: String,
}

/// pin/unpin のオーナーシップ判定に必要な列のみ取得する。
/// `note_visibility::fetch_note_for_visibility` (閲覧者視点の可視性判定
/// 専用) とは目的が異なるため流用しない。
async fn fetch_note_for_pin(
    db: &sqlx::PgPool,
    note_id: Uuid,
) -> Result<Option<PinNoteRow>, AppError> {
    let row = sqlx::query_as::<_, PinNoteRow>(
        "SELECT actor_id, visibility, renote_of_id, ap_id FROM notes WHERE id = $1 AND deleted_at IS NULL",
    )
    .bind(note_id)
    .fetch_optional(db)
    .await?;
    Ok(row)
}

/// `actor_uri()`/featured URL の組み立てに必要なローカルアクターの
/// username を取得する。pin/unpin の認証済みアクターは常にローカルなので
/// `app.services.actor_service.actor_uri` のリモート分岐は不要。
async fn fetch_local_actor_username(db: &sqlx::PgPool, actor_id: Uuid) -> Result<String, AppError> {
    sqlx::query_scalar("SELECT username FROM actors WHERE id = $1")
        .bind(actor_id)
        .fetch_optional(db)
        .await?
        .ok_or_else(|| AppError::new(StatusCode::INTERNAL_SERVER_ERROR, "Actor not found"))
}

/// pin/unpin成功後、フォロワー全員へ Add/Remove アクティビティを配送する。
/// `app/api/mastodon/statuses.py` の pin_status/unpin_status 末尾の
/// 配送ループを共通化したもの。1件の配送失敗が他の配送や本体操作を
/// ロールバックしないPython版の非トランザクション挙動をそのまま踏襲する。
async fn deliver_pin_activity(
    state: &AppState,
    actor_id: Uuid,
    note_ap_id: &str,
    note_id: Uuid,
    kind: &str,
    render: impl Fn(&str, &str, &str, &str) -> serde_json::Value,
) -> Result<(), AppError> {
    let username = fetch_local_actor_username(&state.db, actor_id).await?;
    let server_url = state.config.server_url();
    let actor_uri = format!("{server_url}/users/{username}");
    let target = format!("{server_url}/users/{username}/featured");
    let activity = render(
        &format!("{actor_uri}/{kind}/{note_id}"),
        &actor_uri,
        note_ap_id,
        &target,
    );
    for inbox_url in get_follower_inboxes(&state.db, actor_id).await? {
        enqueue_delivery(state, actor_id, &inbox_url, &activity).await?;
    }
    Ok(())
}

/// `app/api/mastodon/statuses.py` の `pin_status` を移植したもの。
/// Python版と異なり「ノートが存在しない」場合も含め全業務エラーを422で
/// 統一する (Python版のtry/exceptがValueErrorを一律422にマップするのと同じ)。
async fn pin_status(
    State(state): State<AppState>,
    current_user: CurrentUser,
    Path(note_id): Path<Uuid>,
) -> Result<Response, AppError> {
    current_user.require_scope("write:statuses")?;

    let note = fetch_note_for_pin(&state.db, note_id)
        .await?
        .ok_or_else(|| AppError::new(StatusCode::UNPROCESSABLE_ENTITY, "Note not found"))?;

    if note.actor_id != current_user.actor_id {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Can only pin your own notes",
        ));
    }
    if note.visibility == "direct" {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Cannot pin a direct post",
        ));
    }
    if note.renote_of_id.is_some() {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Cannot pin a reblog",
        ));
    }

    let existing: Option<Uuid> =
        sqlx::query_scalar("SELECT id FROM pinned_notes WHERE actor_id = $1 AND note_id = $2")
            .bind(current_user.actor_id)
            .bind(note_id)
            .fetch_optional(&state.db)
            .await?;
    if existing.is_some() {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Already pinned",
        ));
    }

    let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM pinned_notes WHERE actor_id = $1")
        .bind(current_user.actor_id)
        .fetch_one(&state.db)
        .await?;
    if count >= MAX_PINS {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            format!("Maximum {MAX_PINS} pinned notes allowed"),
        ));
    }

    let result = sqlx::query(
        "INSERT INTO pinned_notes (id, actor_id, note_id, position) VALUES ($1, $2, $3, $4)",
    )
    .bind(db::new_id())
    .bind(current_user.actor_id)
    .bind(note_id)
    .bind(count as i32)
    .execute(&state.db)
    .await;

    match result {
        Ok(_) => {}
        Err(sqlx::Error::Database(db_err)) if db_err.code().as_deref() == Some("23505") => {
            return Err(AppError::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "Already pinned",
            ));
        }
        Err(e) => return Err(e.into()),
    }

    deliver_pin_activity(
        &state,
        current_user.actor_id,
        &note.ap_id,
        note_id,
        "add",
        render_add_activity,
    )
    .await?;

    Ok(Json(json!({ "ok": true })).into_response())
}

/// `app/api/mastodon/statuses.py` の `unpin_status` を移植したもの。
/// pinと異なり「ノートが存在しない」は404 (Python版の事前 `get_note_by_id`
/// チェックに対応)、「ピン留めされていない」のみ422。
async fn unpin_status(
    State(state): State<AppState>,
    current_user: CurrentUser,
    Path(note_id): Path<Uuid>,
) -> Result<Response, AppError> {
    current_user.require_scope("write:statuses")?;

    let note = fetch_note_for_pin(&state.db, note_id)
        .await?
        .ok_or_else(|| AppError::not_found("Note not found"))?;

    let result = sqlx::query("DELETE FROM pinned_notes WHERE actor_id = $1 AND note_id = $2")
        .bind(current_user.actor_id)
        .bind(note_id)
        .execute(&state.db)
        .await?;
    if result.rows_affected() == 0 {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Not pinned",
        ));
    }

    deliver_pin_activity(
        &state,
        current_user.actor_id,
        &note.ap_id,
        note_id,
        "remove",
        render_remove_activity,
    )
    .await?;

    Ok(Json(json!({ "ok": true })).into_response())
}
