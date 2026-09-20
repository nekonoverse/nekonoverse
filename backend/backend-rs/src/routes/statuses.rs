//! `app/api/mastodon/statuses.py` のうち、Stage 3 でRust化するブックマーク
//! 書き込みパス (`bookmark`/`unbookmark`) のみを切り出したもの。
//! 投稿本体のCRUD・リアクション・リノート等の巨大な残りの面は Stage 4 以降。

use axum::extract::{Path, State};
use axum::response::{IntoResponse, Response};
use axum::routing::post;
use axum::{Json, Router};
use serde_json::json;
use uuid::Uuid;

use crate::auth::CurrentUser;
use crate::db;
use crate::error::AppError;
use crate::note_visibility::{check_note_visible, fetch_note_for_visibility};
use crate::state::AppState;

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/api/v1/statuses/:note_id/bookmark", post(bookmark_status))
        .route(
            "/api/v1/statuses/:note_id/unbookmark",
            post(unbookmark_status),
        )
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
