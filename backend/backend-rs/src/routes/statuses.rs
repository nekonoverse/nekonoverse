//! `app/api/mastodon/statuses.py` のうち、Stage 3 でRust化したブックマーク
//! 書き込みパス (`bookmark`/`unbookmark`)、Stage 4 で追加したpin/unpin、
//! `get_status` (`GET /api/v1/statuses/{id}`、NoteResponse直列化パイプライン
//! の最初のルート配線)、`delete_status`/`unreblog_status`/`reblog_status`
//! を切り出したもの。同じパスのPUT(`edit_status`)、投稿作成
//! (`create_status`)は未移植(nginx側でメソッド別にPython/Rustへ振り分ける、
//! `nginx/*.conf` 参照)。`reblog_status`は元ノート著者への通知作成
//! (`create_notification`)経由でWeb Push/Discord Webhook配送に依存する
//! ように見えるが、Python版でもこの2つは個別のtry/exceptで囲われ失敗を
//! 握りつぶす契約になっているため、`notification.rs`側でそれらを移植せず
//! 通知行作成本体(重複排除・ブロック/ミュート確認)とアプリ内リアルタイム
//! 通知用のValkey publishのみ実装している(詳細は`notification.rs`参照)。
//! 元ノートの画像へのフォーカルポイント検出・visionタグ付け連携
//! (`face_detect_enabled`/`neko_vision_enabled`)は、対象のサブモジュール
//! 自体がIssue #1139の「スコープ外」節で明示されているため移植しない。

use axum::body::Bytes;
use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use chrono::{DateTime, Utc};
use serde::Deserialize;
use serde_json::{json, Value};
use uuid::Uuid;

use crate::activitypub::{
    render_add_activity, render_announce_activity, render_delete_activity, render_remove_activity,
    render_undo_activity,
};
use crate::auth::{CurrentUser, OptionalUser};
use crate::db;
use crate::delivery::enqueue_delivery;
use crate::error::AppError;
use crate::follows::{get_follower_ids, get_follower_inboxes};
use crate::mastodon_time::to_mastodon_datetime;
use crate::note_response::{
    fetch_note_render_row, get_reaction_summary, note_to_response_json_recursive,
};
use crate::note_visibility::{
    check_note_visible, check_note_visible_optional, fetch_note_for_visibility, NoteVisibilityRow,
};
use crate::notification::{create_notification, publish_notification};
use crate::state::AppState;
use crate::valkey::{channels, publish_envelope, Envelope};

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
        .route("/api/v1/statuses/:note_id/unreblog", post(unreblog_status))
        .route("/api/v1/statuses/:note_id/reblog", post(reblog_status))
        .route(
            "/api/v1/statuses/:note_id",
            get(get_status).delete(delete_status),
        )
}

/// `app/api/mastodon/statuses.py` の `get_status` を移植したもの。
async fn get_status(
    State(state): State<AppState>,
    Path(note_id): Path<Uuid>,
    OptionalUser(user): OptionalUser,
) -> Result<Response, AppError> {
    let visibility_row = fetch_note_for_visibility(&state.db, note_id)
        .await?
        .ok_or_else(|| AppError::not_found("Note not found"))?;
    let viewer_actor_id = user.as_ref().map(|u| u.actor_id);
    if !check_note_visible_optional(&state.db, &visibility_row, viewer_actor_id).await? {
        return Err(AppError::not_found("Note not found"));
    }

    let note = fetch_note_render_row(&state.db, note_id)
        .await?
        .ok_or_else(|| AppError::not_found("Note not found"))?;
    let reactions =
        get_reaction_summary(&state.db, &state.config, note_id, viewer_actor_id).await?;

    let resp = note_to_response_json_recursive(
        &state.db,
        &state.config,
        &state.redis,
        &note,
        reactions,
        viewer_actor_id,
        false,
        false,
    )
    .await?;

    Ok(Json(resp).into_response())
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

#[derive(sqlx::FromRow)]
struct DeleteNoteRow {
    actor_id: Uuid,
    ap_id: String,
}

async fn fetch_note_for_delete(
    db: &sqlx::PgPool,
    note_id: Uuid,
) -> Result<Option<DeleteNoteRow>, AppError> {
    let row = sqlx::query_as::<_, DeleteNoteRow>(
        "SELECT actor_id, ap_id FROM notes WHERE id = $1 AND deleted_at IS NULL",
    )
    .bind(note_id)
    .fetch_optional(db)
    .await?;
    Ok(row)
}

/// `app/api/mastodon/statuses.py` の `delete_status` を移植したもの。
/// neko-search索引からの削除連携(`enqueue_delete`)は、neko-search統合
/// 自体がIssue #1139の「スコープ外」節で明示されている対象のため移植しない。
async fn delete_status(
    State(state): State<AppState>,
    current_user: CurrentUser,
    Path(note_id): Path<Uuid>,
) -> Result<Response, AppError> {
    current_user.require_scope("write:statuses")?;

    let note = fetch_note_for_delete(&state.db, note_id)
        .await?
        .ok_or_else(|| AppError::not_found("Note not found"))?;
    if note.actor_id != current_user.actor_id {
        return Err(AppError::new(StatusCode::FORBIDDEN, "Not your note"));
    }

    sqlx::query("UPDATE notes SET deleted_at = now() WHERE id = $1")
        .bind(note_id)
        .execute(&state.db)
        .await?;

    let username = fetch_local_actor_username(&state.db, current_user.actor_id).await?;
    let actor_uri = format!("{}/users/{username}", state.config.server_url());
    let delete_activity =
        render_delete_activity(&format!("{}/delete", note.ap_id), &actor_uri, &note.ap_id);
    for inbox_url in get_follower_inboxes(&state.db, current_user.actor_id).await? {
        enqueue_delivery(&state, current_user.actor_id, &inbox_url, &delete_activity).await?;
    }

    Ok(StatusCode::NO_CONTENT.into_response())
}

#[derive(sqlx::FromRow)]
struct ReblogNoteRow {
    id: Uuid,
    ap_id: String,
    to: Value,
    cc: Value,
    published: DateTime<Utc>,
}

/// 指定アクター自身による、指定ノートへのリブログ(まだ削除されていないもの)
/// を取得する。
async fn fetch_own_reblog_note(
    db: &sqlx::PgPool,
    actor_id: Uuid,
    original_id: Uuid,
) -> Result<Option<ReblogNoteRow>, AppError> {
    let row = sqlx::query_as::<_, ReblogNoteRow>(
        r#"SELECT id, ap_id, "to", cc, published FROM notes
           WHERE actor_id = $1 AND renote_of_id = $2 AND deleted_at IS NULL"#,
    )
    .bind(actor_id)
    .bind(original_id)
    .fetch_optional(db)
    .await?;
    Ok(row)
}

/// `app/api/mastodon/statuses.py` の `unreblog_status` を移植したもの。
async fn unreblog_status(
    State(state): State<AppState>,
    current_user: CurrentUser,
    Path(note_id): Path<Uuid>,
) -> Result<Response, AppError> {
    current_user.require_scope("write:statuses")?;

    let original_ap_id: Option<String> =
        sqlx::query_scalar("SELECT ap_id FROM notes WHERE id = $1 AND deleted_at IS NULL")
            .bind(note_id)
            .fetch_optional(&state.db)
            .await?;
    let original_ap_id = original_ap_id.ok_or_else(|| AppError::not_found("Note not found"))?;

    let reblog_note = fetch_own_reblog_note(&state.db, current_user.actor_id, note_id)
        .await?
        .ok_or_else(|| AppError::new(StatusCode::UNPROCESSABLE_ENTITY, "Not reblogged"))?;

    sqlx::query("UPDATE notes SET deleted_at = now() WHERE id = $1")
        .bind(reblog_note.id)
        .execute(&state.db)
        .await?;
    sqlx::query("UPDATE notes SET renotes_count = GREATEST(renotes_count - 1, 0) WHERE id = $1")
        .bind(note_id)
        .execute(&state.db)
        .await?;

    let username = fetch_local_actor_username(&state.db, current_user.actor_id).await?;
    let actor_uri = format!("{}/users/{username}", state.config.server_url());
    let announce_activity = render_announce_activity(
        &reblog_note.ap_id,
        &actor_uri,
        &original_ap_id,
        &reblog_note.to,
        &reblog_note.cc,
        &to_mastodon_datetime(reblog_note.published),
    );
    let undo_activity = render_undo_activity(
        &format!("{}/undo", reblog_note.ap_id),
        &actor_uri,
        &announce_activity,
    );
    for inbox_url in get_follower_inboxes(&state.db, current_user.actor_id).await? {
        enqueue_delivery(&state, current_user.actor_id, &inbox_url, &undo_activity).await?;
    }

    Ok(Json(json!({ "ok": true })).into_response())
}

#[derive(Deserialize, Default)]
struct ReblogBody {
    visibility: Option<String>,
}

/// Mastodon互換の可視性ランク。数字が小さいほど公開範囲が広い。
/// `_RANK`(`app/api/mastodon/statuses.py`)と同一。
fn visibility_rank(visibility: &str) -> i32 {
    match visibility {
        "public" => 0,
        "unlisted" => 1,
        "followers" => 2,
        "direct" => 3,
        _ => 3,
    }
}

/// `check_note_visible` 用の `NoteVisibilityRow` には無い `ap_id` を
/// 別途取得する(reblogのAnnounceアクティビティ組み立てに必要)。
async fn fetch_note_ap_id(db: &sqlx::PgPool, note_id: Uuid) -> Result<String, AppError> {
    sqlx::query_scalar("SELECT ap_id FROM notes WHERE id = $1")
        .bind(note_id)
        .fetch_one(db)
        .await
        .map_err(AppError::from)
}

/// `app/api/mastodon/statuses.py` の `reblog_status` を移植したもの。
/// 元ノートの画像へのフォーカルポイント検出・visionタグ付け連携
/// (スコープ外)、Web Push/Discord Webhook配送(`notification.rs`参照)は
/// 移植しない。
async fn reblog_status(
    State(state): State<AppState>,
    current_user: CurrentUser,
    Path(note_id): Path<Uuid>,
    body: Bytes,
) -> Result<Response, AppError> {
    current_user.require_scope("write:statuses")?;

    let requested_visibility: Option<String> = if body.is_empty() {
        None
    } else {
        serde_json::from_slice::<ReblogBody>(&body)
            .ok()
            .and_then(|b| b.visibility)
    };

    let original: NoteVisibilityRow = fetch_note_for_visibility(&state.db, note_id)
        .await?
        .ok_or_else(|| AppError::not_found("Note not found"))?;
    if !check_note_visible(&state.db, &original, current_user.actor_id).await? {
        return Err(AppError::not_found("Note not found"));
    }

    if original.visibility == "direct" {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Cannot reblog a direct post",
        ));
    }
    if original.visibility == "followers" && original.actor_id != current_user.actor_id {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Cannot reblog a private post",
        ));
    }

    let mut reblog_vis = requested_visibility.unwrap_or_else(|| original.visibility.clone());
    if reblog_vis == "private" {
        reblog_vis = "followers".to_string();
    }
    if !matches!(reblog_vis.as_str(), "public" | "unlisted" | "followers") {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Cannot reblog with direct visibility",
        ));
    }
    if visibility_rank(&reblog_vis) < visibility_rank(&original.visibility) {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Cannot reblog with wider visibility than the original",
        ));
    }

    let existing_reblog: Option<Uuid> = sqlx::query_scalar(
        "SELECT id FROM notes WHERE actor_id = $1 AND renote_of_id = $2 AND deleted_at IS NULL",
    )
    .bind(current_user.actor_id)
    .bind(note_id)
    .fetch_optional(&state.db)
    .await?;
    if existing_reblog.is_some() {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Already reblogged",
        ));
    }

    let original_ap_id = fetch_note_ap_id(&state.db, note_id).await?;

    let reblog_id = db::new_id();
    let ap_id = format!("{}/notes/{reblog_id}", state.config.server_url());

    const PUBLIC: &str = "https://www.w3.org/ns/activitystreams#Public";
    let followers_url: Option<String> =
        sqlx::query_scalar("SELECT followers_url FROM actors WHERE id = $1")
            .bind(current_user.actor_id)
            .fetch_one(&state.db)
            .await?;
    let followers_url = followers_url.unwrap_or_default();
    let (to_list, cc_list) = match reblog_vis.as_str() {
        "public" => (json!([PUBLIC]), json!([followers_url])),
        "unlisted" => (json!([followers_url]), json!([PUBLIC])),
        _ => (json!([followers_url]), json!([])),
    };

    let published = db::now();
    sqlx::query(
        r#"
        INSERT INTO notes (
            id, ap_id, actor_id, content, visibility, sensitive, "to", cc, published,
            replies_count, reactions_count, renotes_count, local, is_poll, poll_multiple,
            is_talk, renote_of_id, renote_of_ap_id
        ) VALUES (
            $1, $2, $3, '', $4, false, $5, $6, $7,
            0, 0, 0, true, false, false,
            false, $8, $9
        )
        "#,
    )
    .bind(reblog_id)
    .bind(&ap_id)
    .bind(current_user.actor_id)
    .bind(&reblog_vis)
    .bind(&to_list)
    .bind(&cc_list)
    .bind(published)
    .bind(note_id)
    .bind(&original_ap_id)
    .execute(&state.db)
    .await?;

    sqlx::query("UPDATE notes SET renotes_count = renotes_count + 1 WHERE id = $1")
        .bind(note_id)
        .execute(&state.db)
        .await?;

    // 元ノートの著者がローカルなら通知する。Web Push/Discord Webhook配送は
    // 移植しない(モジュール冒頭のコメント参照)。
    let original_author_domain: Option<String> =
        sqlx::query_scalar("SELECT domain FROM actors WHERE id = $1")
            .bind(original.actor_id)
            .fetch_optional(&state.db)
            .await?
            .flatten();
    if original_author_domain.is_none() {
        if let Some(notification) = create_notification(
            &state.db,
            "renote",
            original.actor_id,
            Some(current_user.actor_id),
            Some(note_id),
            None,
        )
        .await?
        {
            publish_notification(&state.redis, &notification).await;
        }
    }

    let username = fetch_local_actor_username(&state.db, current_user.actor_id).await?;
    let actor_uri = format!("{}/users/{username}", state.config.server_url());
    let announce_activity = render_announce_activity(
        &ap_id,
        &actor_uri,
        &original_ap_id,
        &to_list,
        &cc_list,
        &to_mastodon_datetime(published),
    );
    for inbox_url in get_follower_inboxes(&state.db, current_user.actor_id).await? {
        enqueue_delivery(
            &state,
            current_user.actor_id,
            &inbox_url,
            &announce_activity,
        )
        .await?;
    }

    // ストリーミングイベントを発行し、フォロワーがリブログをリアルタイムで
    // 確認できるようにする(ベストエフォート、失敗してもリブログは失敗させない)。
    let update_envelope = Envelope {
        event: "update",
        payload: json!({ "id": reblog_id.to_string() }),
    };
    if reblog_vis == "public" {
        publish_envelope(&state.redis, channels::TIMELINE_PUBLIC, &update_envelope).await;
    }
    for follower_id in get_follower_ids(&state.db, current_user.actor_id).await? {
        publish_envelope(
            &state.redis,
            &channels::timeline_home(follower_id),
            &update_envelope,
        )
        .await;
    }
    publish_envelope(
        &state.redis,
        &channels::timeline_home(current_user.actor_id),
        &update_envelope,
    )
    .await;

    let reblog_row = fetch_note_render_row(&state.db, reblog_id)
        .await?
        .ok_or_else(|| AppError::new(StatusCode::INTERNAL_SERVER_ERROR, "Note not found"))?;
    let resp = note_to_response_json_recursive(
        &state.db,
        &state.config,
        &state.redis,
        &reblog_row,
        Vec::new(),
        Some(current_user.actor_id),
        false,
        false,
    )
    .await?;

    Ok(Json(resp).into_response())
}
