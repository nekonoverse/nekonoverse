//! `app/api/mastodon/statuses.py` のうち、Stage 3 でRust化したブックマーク
//! 書き込みパス (`bookmark`/`unbookmark`)、Stage 4 で追加したpin/unpin、
//! `get_status` (`GET /api/v1/statuses/{id}`、NoteResponse直列化パイプライン
//! の最初のルート配線)、`delete_status`/`unreblog_status`/`reblog_status`/
//! `create_status` を切り出したもの。同じパスのPUT(`edit_status`)は
//! 未移植(nginx側でメソッド別にPython/Rustへ振り分ける、`nginx/*.conf`
//! 参照)。`reblog_status`/`create_status`は元ノート著者・返信先・メンション先
//! への通知作成(`create_notification`)経由でWeb Push/Discord Webhook配送に
//! 依存するように見えるが、Python版でもこの2つは個別のtry/exceptで囲われ
//! 失敗を握りつぶす契約になっているため、`notification.rs`側でそれらを移植せず
//! 通知行作成本体(重複排除・ブロック/ミュート確認)とアプリ内リアルタイム
//! 通知用のValkey publishのみ実装している(詳細は`notification.rs`参照)。
//! 元ノートの画像へのフォーカルポイント検出・visionタグ付け連携
//! (`face_detect_enabled`/`neko_vision_enabled`)、検索インデックス連携
//! (`neko_search_enabled`)は、対象のサブモジュール自体がIssue #1139の
//! 「スコープ外」節で明示されているため移植しない。URL要約カード抽出の
//! エンキュー(`summary_proxy_queue`)も、backend-rs にまだ存在しない設定
//! (`summary_proxy_url`)を要する別個のサブシステムのため同様に見送る —
//! 未対応の間はプレビューカードが付かないだけで投稿自体は成功する
//! (Python版でもキュー投入はベストエフォートで本体の成否に影響しない)。
//! `create_status` のメンション解決はDB上に既知のアクター (ローカル/既知の
//! リモート) のみが対象で、`resolve_webfinger`/`fetch_remote_actor` を要する
//! 未知のリモートメンション解決は移植しない (Stage 4のaccounts系エンドポイント
//! で確立した既存の分割方針と同じ)。realtime pub/subの配信先フィルタ
//! (exclusiveリスト除外・リストタイムライン配信)も `list_service` が
//! まだ移植されていないため未対応 — 実際のタイムライン取得(引き続き
//! Python側)はDBを直接見るため正しくフィルタされる。影響があるのは
//! 「新着があります」というSSEシグナルのみで、クライアントは結局REST APIを
//! 再取得して正しい結果を得る。
use axum::body::Bytes;
use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use chrono::{DateTime, Utc};
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::HashSet;
use uuid::Uuid;

use crate::activitypub::{
    render_add_activity, render_announce_activity, render_create_activity, render_delete_activity,
    render_remove_activity, render_undo_activity, truthy_string, EmojiTagData, HashtagTagData,
    NoteRenderData,
};
use crate::auth::{CurrentUser, OptionalUser};
use crate::db;
use crate::delivery::enqueue_delivery;
use crate::error::AppError;
use crate::follows::{get_follower_ids, get_follower_inboxes};
use crate::hashtag::{extract_hashtags, upsert_hashtags};
use crate::mastodon_time::to_mastodon_datetime;
use crate::note_response::{
    fetch_note_render_row, get_reaction_summary, note_to_response_json_recursive,
};
use crate::note_visibility::{
    check_note_visible, check_note_visible_optional, fetch_note_for_visibility, NoteVisibilityRow,
};
use crate::notification::{create_notification, publish_notification};
use crate::routes::actor::fetch_attachments_by_note;
use crate::shortcode::find_shortcodes;
use crate::state::AppState;
use crate::text_html::{extract_mentions, text_to_html};
use crate::valkey::{channels, publish_envelope, Envelope};

/// `app.services.pinned_note_service.MAX_PINS` と同一。
const MAX_PINS: i64 = 5;

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/api/v1/statuses", post(create_status))
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

#[derive(Deserialize)]
struct PollCreateRequest {
    options: Vec<String>,
    #[serde(default = "default_poll_expires_in")]
    expires_in: i64,
    #[serde(default)]
    multiple: bool,
}

fn default_poll_expires_in() -> i64 {
    86400
}

fn default_create_visibility() -> String {
    "public".to_string()
}

/// `app/schemas/note.py` の `NoteCreateRequest`/`PollCreateRequest` を
/// 移植したもの。`content` は `alias="status"`/`populate_by_name=True` と同じく
/// `content`/`status` どちらのJSONキーでも受け付ける
/// (masto.js 等の実クライアントは `status` を送る、`tests/mastodon-client/`
/// 参照)。
#[derive(Deserialize)]
struct NoteCreateRequest {
    #[serde(default, alias = "status")]
    content: String,
    #[serde(default = "default_create_visibility")]
    visibility: String,
    #[serde(default)]
    sensitive: bool,
    #[serde(default)]
    spoiler_text: Option<String>,
    #[serde(default)]
    in_reply_to_id: Option<Uuid>,
    #[serde(default)]
    media_ids: Vec<Uuid>,
    #[serde(default)]
    quote_id: Option<Uuid>,
    #[serde(default)]
    poll: Option<PollCreateRequest>,
}

/// `NoteCreateRequest`/`PollCreateRequest` の pydantic `Field`/`field_validator`/
/// `model_validator` を移植したもの。Python版の pydantic ValidationError は
/// 自動的に422を返すが、ここでは pin/reblog 等の既存業務エラーと同じく
/// 全違反を422+平文メッセージに統一する
/// (`pin_status`冒頭のコメント「Python版のtry/exceptがValueErrorを一律422に
/// マップするのと同じ」と同じ割り切り)。
fn validate_create_request(body: &NoteCreateRequest) -> Result<(), AppError> {
    if body.content.chars().count() > 5000 {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "content must be 5000 characters or fewer",
        ));
    }
    if !matches!(
        body.visibility.as_str(),
        "public" | "unlisted" | "followers" | "private" | "direct"
    ) {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Invalid visibility",
        ));
    }
    if let Some(spoiler) = &body.spoiler_text {
        if spoiler.chars().count() > 500 {
            return Err(AppError::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "spoiler_text must be 500 characters or fewer",
            ));
        }
    }
    if body.media_ids.len() > 4 {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "media_ids must contain 4 or fewer items",
        ));
    }
    if let Some(poll) = &body.poll {
        if poll.options.len() < 2 || poll.options.len() > 10 {
            return Err(AppError::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "poll must have between 2 and 10 options",
            ));
        }
        for opt in &poll.options {
            if opt.chars().count() > 200 {
                return Err(AppError::new(
                    StatusCode::UNPROCESSABLE_ENTITY,
                    "Poll option must be 200 characters or fewer",
                ));
            }
            if opt.trim().is_empty() {
                return Err(AppError::new(
                    StatusCode::UNPROCESSABLE_ENTITY,
                    "Poll option cannot be empty",
                ));
            }
        }
        if !(300..=2_592_000).contains(&poll.expires_in) {
            return Err(AppError::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "poll.expires_in must be between 300 and 2592000 seconds",
            ));
        }
    }
    if body.content.trim().is_empty() && body.media_ids.is_empty() {
        return Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Content or media is required",
        ));
    }
    Ok(())
}

#[derive(sqlx::FromRow)]
struct CurrentActorInfo {
    username: String,
    followers_url: Option<String>,
}

async fn fetch_current_actor_info(
    db: &sqlx::PgPool,
    actor_id: Uuid,
) -> Result<CurrentActorInfo, AppError> {
    sqlx::query_as("SELECT username, followers_url FROM actors WHERE id = $1")
        .bind(actor_id)
        .fetch_one(db)
        .await
        .map_err(Into::into)
}

/// `app.services.actor_service.actor_uri` を移植したもの。ローカルアクター
/// (`domain IS NULL`) は `settings.server_url` から導出して正しいスキームを
/// 保証し、リモートアクターは保存済みの `ap_id` をそのまま使う。
fn actor_uri_for(
    config: &crate::config::Config,
    username: &str,
    domain: Option<&str>,
    ap_id: &str,
) -> String {
    match domain {
        None => format!("{}/users/{username}", config.server_url()),
        Some(_) => ap_id.to_string(),
    }
}

#[derive(sqlx::FromRow, Clone)]
struct MentionActorRow {
    id: Uuid,
    username: String,
    domain: Option<String>,
    ap_id: String,
    inbox_url: String,
    shared_inbox_url: Option<String>,
}

/// `app.services.actor_service.get_actor_by_username` のうち、DB上に既知の
/// アクター(ローカル/既に取り込み済みのリモート)を引く部分のみを移植した
/// もの。未知のリモートアクターの `resolve_webfinger` によるフェッチ解決は
/// 移植しない(モジュール冒頭のコメント参照)。
async fn fetch_actor_by_username(
    db: &sqlx::PgPool,
    username: &str,
    domain: Option<&str>,
) -> Result<Option<MentionActorRow>, AppError> {
    let row = match domain {
        None => {
            sqlx::query_as::<_, MentionActorRow>(
                "SELECT id, username, domain, ap_id, inbox_url, shared_inbox_url FROM actors \
                 WHERE domain IS NULL AND username = lower($1)",
            )
            .bind(username)
            .fetch_optional(db)
            .await?
        }
        Some(d) => {
            sqlx::query_as::<_, MentionActorRow>(
                "SELECT id, username, domain, ap_id, inbox_url, shared_inbox_url FROM actors \
                 WHERE domain = $2 AND lower(username) = lower($1)",
            )
            .bind(username)
            .bind(d)
            .fetch_optional(db)
            .await?
        }
    };
    Ok(row)
}

#[derive(sqlx::FromRow)]
struct ReplyParentInfo {
    id: Uuid,
    ap_id: String,
    actor_id: Uuid,
    actor_username: String,
    actor_ap_id: String,
    actor_domain: Option<String>,
    actor_inbox_url: String,
    actor_shared_inbox_url: Option<String>,
}

async fn fetch_reply_parent_info(
    db: &sqlx::PgPool,
    note_id: Uuid,
) -> Result<Option<ReplyParentInfo>, AppError> {
    let row = sqlx::query_as::<_, ReplyParentInfo>(
        r#"SELECT n.id, n.ap_id, a.id AS actor_id, a.username AS actor_username,
           a.ap_id AS actor_ap_id, a.domain AS actor_domain, a.inbox_url AS actor_inbox_url,
           a.shared_inbox_url AS actor_shared_inbox_url
           FROM notes n JOIN actors a ON a.id = n.actor_id
           WHERE n.id = $1 AND n.deleted_at IS NULL"#,
    )
    .bind(note_id)
    .fetch_optional(db)
    .await?;
    Ok(row)
}

/// 添付ファイルの所有権確認込みで `drive_files` をバッチ取得する。
/// `app.services.drive_service.get_drive_files_by_ids` (入力順序を保持) +
/// `create_status` route側の `if drive_file.owner_id == user.id` フィルタを
/// 合わせて移植したもの。存在しない/他人所有の media_id は黙ってスキップする
/// (Python版と同じ、エラーにしない)。
async fn fetch_owned_drive_file_ids(
    db: &sqlx::PgPool,
    media_ids: &[Uuid],
    owner_user_id: Uuid,
) -> Result<Vec<Uuid>, AppError> {
    if media_ids.is_empty() {
        return Ok(Vec::new());
    }
    #[derive(sqlx::FromRow)]
    struct Row {
        id: Uuid,
        owner_id: Option<Uuid>,
    }
    let rows: Vec<Row> = sqlx::query_as("SELECT id, owner_id FROM drive_files WHERE id = ANY($1)")
        .bind(media_ids)
        .fetch_all(db)
        .await?;
    let owned: HashSet<Uuid> = rows
        .into_iter()
        .filter(|r| r.owner_id == Some(owner_user_id))
        .map(|r| r.id)
        .collect();
    Ok(media_ids
        .iter()
        .filter(|id| owned.contains(id))
        .copied()
        .collect())
}

#[derive(sqlx::FromRow)]
struct EmojiTagRow {
    shortcode: String,
    url: String,
    aliases: Option<Value>,
    license: Option<String>,
    is_sensitive: bool,
    author: Option<String>,
    description: Option<String>,
    copy_permission: Option<String>,
    usage_info: Option<String>,
    is_based_on: Option<String>,
}

/// `app.services.emoji_service.get_emojis_by_shortcodes(db, shortcodes, None)` +
/// `if not emoji.local_only` フィルタを移植したもの。AP Create配送用の
/// カスタム絵文字タグ一覧を組み立てる(表示用の `note_to_response` 側の絵文字
/// 解決は `note_response.rs::resolve_note_and_actor_emojis` が挿入後のDBを
/// 直接見るため、こことは独立)。
async fn fetch_local_emoji_tags(
    db: &sqlx::PgPool,
    config: &crate::config::Config,
    shortcodes: &HashSet<String>,
) -> Result<Vec<EmojiTagData>, AppError> {
    if shortcodes.is_empty() {
        return Ok(Vec::new());
    }
    let codes: Vec<String> = shortcodes.iter().cloned().collect();
    let rows: Vec<EmojiTagRow> = sqlx::query_as(
        "SELECT shortcode, url, aliases, license, is_sensitive, author, description, \
         copy_permission, usage_info, is_based_on FROM custom_emojis \
         WHERE domain IS NULL AND local_only = false AND shortcode = ANY($1)",
    )
    .bind(&codes)
    .fetch_all(db)
    .await?;
    Ok(rows
        .into_iter()
        .map(|e| EmojiTagData {
            id: format!("{}/emojis/{}", config.server_url(), e.shortcode),
            shortcode: e.shortcode,
            url: e.url,
            aliases: e.aliases,
            license: truthy_string(e.license),
            is_sensitive: e.is_sensitive,
            author: truthy_string(e.author),
            description: truthy_string(e.description),
            copy_permission: truthy_string(e.copy_permission),
            usage_info: truthy_string(e.usage_info),
            is_based_on: truthy_string(e.is_based_on),
        })
        .collect())
}

/// `app/api/mastodon/statuses.py` の `create_status`(ルート層の
/// `in_reply_to_id`検証・可視性狭め処理)+ `app/services/note_service.py` の
/// `create_note`(本体)を移植したもの。モジュール冒頭のコメントに記載の
/// 通り、未知のリモートメンション解決(WebFinger)・URL要約カード抽出・
/// neko-vision/neko-search連携・realtime pub/subのexclusiveリスト/
/// リストタイムライン配信は対象外。
async fn create_status(
    State(state): State<AppState>,
    current_user: CurrentUser,
    body: Bytes,
) -> Result<Response, AppError> {
    current_user.require_scope("write:statuses")?;

    let payload: NoteCreateRequest = serde_json::from_slice(&body).map_err(|e| {
        AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            format!("Invalid request body: {e}"),
        )
    })?;
    validate_create_request(&payload)?;

    // CW付きノートは自動的にsensitiveにする (Mastodon互換)。
    let sensitive = payload.sensitive
        || payload
            .spoiler_text
            .as_deref()
            .is_some_and(|s| !s.is_empty());

    let mut visibility = if payload.visibility == "private" {
        "followers".to_string()
    } else {
        payload.visibility.clone()
    };

    // ---- 返信先の検証 + 可視性狭め ----
    let mut parent: Option<ReplyParentInfo> = None;
    if let Some(parent_id) = payload.in_reply_to_id {
        let parent_visibility_row = fetch_note_for_visibility(&state.db, parent_id)
            .await?
            .ok_or_else(|| AppError::not_found("Reply target not found"))?;
        if !check_note_visible(&state.db, &parent_visibility_row, current_user.actor_id).await? {
            return Err(AppError::not_found("Reply target not found"));
        }
        // リプライの公開範囲は親ノートより広くできない。
        let parent_rank = visibility_rank(&parent_visibility_row.visibility);
        let reply_rank = visibility_rank(&visibility);
        if reply_rank < parent_rank {
            visibility = parent_visibility_row.visibility.clone();
        }
        parent = fetch_reply_parent_info(&state.db, parent_id).await?;
    }

    // ---- 可視性に基づいてto/ccを構築 ----
    let current_actor = fetch_current_actor_info(&state.db, current_user.actor_id).await?;
    const PUBLIC: &str = "https://www.w3.org/ns/activitystreams#Public";
    let followers_url = current_actor.followers_url.clone().unwrap_or_default();
    let mut to_list: Vec<String> = Vec::new();
    let mut cc_list: Vec<String> = Vec::new();
    match visibility.as_str() {
        "public" => {
            to_list.push(PUBLIC.to_string());
            cc_list.push(followers_url.clone());
        }
        "unlisted" => {
            to_list.push(followers_url.clone());
            cc_list.push(PUBLIC.to_string());
        }
        "followers" => {
            to_list.push(followers_url.clone());
        }
        _ => {}
    }

    // ---- メンションを抽出してcc/toに追加 ----
    let mut mention_data: Vec<Value> = Vec::new();
    let mut mention_actors: Vec<MentionActorRow> = Vec::new();
    for (username, domain) in extract_mentions(&payload.content) {
        let Some(actor) = fetch_actor_by_username(&state.db, &username, domain.as_deref()).await?
        else {
            continue;
        };
        let uri = actor_uri_for(
            &state.config,
            &actor.username,
            actor.domain.as_deref(),
            &actor.ap_id,
        );
        mention_data.push(json!({
            "ap_id": uri,
            "username": actor.username,
            "domain": actor.domain,
        }));
        if visibility == "direct" {
            if !to_list.contains(&uri) {
                to_list.push(uri);
            }
        } else if !cc_list.contains(&uri) {
            cc_list.push(uri);
        }
        mention_actors.push(actor);
    }

    // ---- リプライ先の著者をcc/toに追加 ----
    if let Some(parent) = &parent {
        let parent_uri = actor_uri_for(
            &state.config,
            &parent.actor_username,
            parent.actor_domain.as_deref(),
            &parent.actor_ap_id,
        );
        if visibility == "direct" {
            if !to_list.contains(&parent_uri) {
                to_list.push(parent_uri);
            }
        } else if !cc_list.contains(&parent_uri) {
            cc_list.push(parent_uri);
        }
    }

    // ---- 引用ノートの解決 (閲覧権限のないノートは黙って無視) ----
    let mut quote_id = payload.quote_id;
    let mut quote_ap_id: Option<String> = None;
    let mut quote_actor_id: Option<Uuid> = None;
    let mut quote_actor_domain: Option<String> = None;
    if let Some(qid) = quote_id {
        match fetch_note_for_visibility(&state.db, qid).await? {
            Some(quote_row)
                if check_note_visible(&state.db, &quote_row, current_user.actor_id).await? =>
            {
                quote_ap_id = Some(fetch_note_ap_id(&state.db, qid).await?);
                quote_actor_domain = sqlx::query_scalar("SELECT domain FROM actors WHERE id = $1")
                    .bind(quote_row.actor_id)
                    .fetch_optional(&state.db)
                    .await?
                    .flatten();
                quote_actor_id = Some(quote_row.actor_id);
            }
            _ => {
                quote_id = None;
            }
        }
    }

    let html_content = text_to_html(&payload.content, &state.config.server_url());
    let note_id = db::new_id();
    let ap_id = format!("{}/notes/{note_id}", state.config.server_url());
    let published = db::now();

    let is_poll = payload.poll.is_some();
    let (poll_options_value, poll_expires_at, poll_multiple) = match &payload.poll {
        Some(poll) => {
            let options: Vec<Value> = poll
                .options
                .iter()
                .map(|opt| json!({ "title": opt, "votes_count": 0 }))
                .collect();
            (
                Some(json!(options)),
                Some(published + chrono::Duration::seconds(poll.expires_in)),
                poll.multiple,
            )
        }
        None => (None, None, false),
    };

    let in_reply_to_ap_id = parent.as_ref().map(|p| p.ap_id.clone());

    sqlx::query(
        r#"
        INSERT INTO notes (
            id, ap_id, actor_id, in_reply_to_id, in_reply_to_ap_id, quote_id, quote_ap_id,
            content, source, visibility, sensitive, spoiler_text, "to", cc, published,
            replies_count, reactions_count, renotes_count, mentions, local,
            is_poll, poll_options, poll_expires_at, poll_multiple, is_talk
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7,
            $8, $9, $10, $11, $12, $13, $14, $15,
            0, 0, 0, $16, true,
            $17, $18, $19, $20, false
        )
        "#,
    )
    .bind(note_id)
    .bind(&ap_id)
    .bind(current_user.actor_id)
    .bind(payload.in_reply_to_id)
    .bind(&in_reply_to_ap_id)
    .bind(quote_id)
    .bind(&quote_ap_id)
    .bind(&html_content)
    .bind(&payload.content)
    .bind(&visibility)
    .bind(sensitive)
    .bind(&payload.spoiler_text)
    .bind(json!(to_list))
    .bind(json!(cc_list))
    .bind(published)
    .bind(json!(mention_data))
    .bind(is_poll)
    .bind(&poll_options_value)
    .bind(poll_expires_at)
    .bind(poll_multiple)
    .execute(&state.db)
    .await?;

    if let Some(parent) = &parent {
        sqlx::query("UPDATE notes SET replies_count = replies_count + 1 WHERE id = $1")
            .bind(parent.id)
            .execute(&state.db)
            .await?;
    }

    // ---- メディア添付 ----
    if !payload.media_ids.is_empty() {
        let owned_ids =
            fetch_owned_drive_file_ids(&state.db, &payload.media_ids, current_user.id).await?;
        for (position, drive_file_id) in owned_ids.into_iter().enumerate() {
            sqlx::query(
                "INSERT INTO note_attachments (id, note_id, drive_file_id, position) VALUES ($1, $2, $3, $4)",
            )
            .bind(db::new_id())
            .bind(note_id)
            .bind(drive_file_id)
            .bind(position as i32)
            .execute(&state.db)
            .await?;
        }
    }

    // ---- ハッシュタグの抽出とupsert ----
    let hashtag_names = extract_hashtags(&payload.content);
    if !hashtag_names.is_empty() {
        upsert_hashtags(&state.db, note_id, &hashtag_names).await?;
    }

    // ---- AP連合タグ用にカスタム絵文字ショートコードを抽出 ----
    let mut shortcodes = HashSet::new();
    find_shortcodes(&payload.content, &mut shortcodes);
    let emoji_tags = fetch_local_emoji_tags(&state.db, &state.config, &shortcodes).await?;

    // ---- フォロワーとメンション先のリモートユーザーに配送 ----
    let hashtags_render: Vec<HashtagTagData> = hashtag_names
        .iter()
        .map(|name| HashtagTagData {
            name: name.clone(),
            href: format!("{}/tags/{name}", state.config.server_url()),
        })
        .collect();

    let attachments = fetch_attachments_by_note(&state.db, &[note_id], &state.config.media_url())
        .await?
        .remove(&note_id)
        .unwrap_or_default();

    let preferences: Option<Value> =
        sqlx::query_scalar("SELECT preferences FROM users WHERE id = $1")
            .bind(current_user.id)
            .fetch_optional(&state.db)
            .await?
            .flatten();
    let source_media_type = (!payload.content.is_empty()).then(|| {
        crate::activitypub::resolve_source_media_type(&payload.content, preferences.as_ref())
            .to_string()
    });

    let actor_uri_self = format!(
        "{}/users/{}",
        state.config.server_url(),
        current_actor.username
    );
    let note_url = format!("{}/notes/{note_id}", state.config.server_url());

    let render_data = NoteRenderData {
        ap_id: ap_id.clone(),
        is_poll,
        attributed_to: actor_uri_self,
        content: html_content,
        published,
        to: json!(to_list),
        cc: json!(cc_list),
        note_url,
        updated_at: None,
        source: Some(payload.content.clone()),
        source_media_type,
        sensitive,
        spoiler_text: payload.spoiler_text.clone(),
        in_reply_to_ap_id,
        quote_ap_id,
        mentions: Some(json!(mention_data)),
        attachments,
        poll_options: poll_options_value,
        poll_expires_at,
        poll_multiple,
        is_talk: false,
        hashtags: hashtags_render,
        emoji_tags,
    };
    let activity = render_create_activity(&render_data);

    let mut inboxes: HashSet<String> = HashSet::new();
    if visibility != "direct" {
        inboxes.extend(get_follower_inboxes(&state.db, current_user.actor_id).await?);
    }
    for actor in &mention_actors {
        if actor.domain.is_some() {
            inboxes.insert(
                actor
                    .shared_inbox_url
                    .clone()
                    .unwrap_or_else(|| actor.inbox_url.clone()),
            );
        }
    }
    if let Some(parent) = &parent {
        if parent.actor_domain.is_some() {
            inboxes.insert(
                parent
                    .actor_shared_inbox_url
                    .clone()
                    .unwrap_or_else(|| parent.actor_inbox_url.clone()),
            );
        }
    }
    for inbox_url in inboxes {
        enqueue_delivery(&state, current_user.actor_id, &inbox_url, &activity).await?;
    }

    // ---- 通知を送信 (リプライ→メンション→引用、重複通知を防止) ----
    let mut reply_recipient_id: Option<Uuid> = None;
    if let Some(parent) = &parent {
        if parent.actor_domain.is_none() {
            reply_recipient_id = Some(parent.actor_id);
            if let Some(notification) = create_notification(
                &state.db,
                "reply",
                parent.actor_id,
                Some(current_user.actor_id),
                Some(note_id),
                None,
            )
            .await?
            {
                publish_notification(&state.redis, &notification).await;
            }
        }
    }

    let mut mention_recipient_ids: HashSet<Uuid> = HashSet::new();
    for actor in &mention_actors {
        if actor.domain.is_none() && Some(actor.id) != reply_recipient_id {
            if let Some(notification) = create_notification(
                &state.db,
                "mention",
                actor.id,
                Some(current_user.actor_id),
                Some(note_id),
                None,
            )
            .await?
            {
                publish_notification(&state.redis, &notification).await;
                mention_recipient_ids.insert(actor.id);
            }
        }
    }

    if let Some(actor_id) = quote_actor_id {
        if quote_actor_domain.is_none()
            && Some(actor_id) != reply_recipient_id
            && !mention_recipient_ids.contains(&actor_id)
        {
            if let Some(notification) = create_notification(
                &state.db,
                "quote",
                actor_id,
                Some(current_user.actor_id),
                Some(note_id),
                None,
            )
            .await?
            {
                publish_notification(&state.redis, &notification).await;
            }
        }
    }

    // ---- Valkey pub/sub経由でリアルタイムイベントをパブリッシュ ----
    let update_envelope = Envelope {
        event: "update",
        payload: json!({ "id": note_id.to_string() }),
    };
    if visibility == "public" {
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

    // statuses_countキャッシュを無効化 (ベストエフォート)。
    {
        let mut redis_conn = state.redis.clone();
        let _: Result<(), _> = redis::AsyncCommands::del(
            &mut redis_conn,
            format!("perf:statuses_count:{}", current_user.actor_id),
        )
        .await;
    }

    let note_row = fetch_note_render_row(&state.db, note_id)
        .await?
        .ok_or_else(|| AppError::new(StatusCode::INTERNAL_SERVER_ERROR, "Note not found"))?;
    let resp = note_to_response_json_recursive(
        &state.db,
        &state.config,
        &state.redis,
        &note_row,
        Vec::new(),
        Some(current_user.actor_id),
        false,
        false,
    )
    .await?;

    Ok((StatusCode::CREATED, Json(resp)).into_response())
}
