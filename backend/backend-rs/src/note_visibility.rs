//! `app/services/note_service.py` の単一ノート版可視性判定
//! (`check_note_visible` / 内部の `_visibility_requirements`) を移植したもの。
//!
//! 一覧APIの `filter_visible_notes`(複数ノートをまとめてフォロー確認する
//! バッチ版)はここでは移植しない。書き込み系エンドポイント(bookmark等)が
//! 対象ノート1件だけを都度チェックする用途に限定している。

use chrono::{DateTime, Utc};
use serde_json::Value;
use sqlx::PgPool;
use uuid::Uuid;

use crate::error::AppError;

#[derive(sqlx::FromRow)]
pub struct NoteVisibilityRow {
    pub id: Uuid,
    pub actor_id: Uuid,
    pub visibility: String,
    pub published: DateTime<Utc>,
    pub mentions: Option<Value>,
    pub make_notes_hidden_before: Option<i64>,
    pub make_notes_followers_only_before: Option<i64>,
}

/// `app.services.note_service.get_note_by_id` (可視性判定に必要な列のみ) 相当。
/// `deleted_at IS NULL` の削除済みでないノートのみ返す。
pub async fn fetch_note_for_visibility(
    db: &PgPool,
    note_id: Uuid,
) -> Result<Option<NoteVisibilityRow>, AppError> {
    let row = sqlx::query_as::<_, NoteVisibilityRow>(
        r#"
        SELECT n.id, n.actor_id, n.visibility, n.published, n.mentions,
               a.make_notes_hidden_before, a.make_notes_followers_only_before
        FROM notes n
        JOIN actors a ON a.id = n.actor_id
        WHERE n.id = $1 AND n.deleted_at IS NULL
        "#,
    )
    .bind(note_id)
    .fetch_optional(db)
    .await?;
    Ok(row)
}

/// `app.services.note_service.check_note_visible` (単一ノート版) を移植したもの。
pub async fn check_note_visible(
    db: &PgPool,
    note: &NoteVisibilityRow,
    viewer_actor_id: Uuid,
) -> Result<bool, AppError> {
    // 作者は自分のノートを常に閲覧可能。
    if note.actor_id == viewer_actor_id {
        return Ok(true);
    }

    let mut need_follow = false;

    // Misskey互換: make_notes_hidden_before より前のノートを全員から非表示。
    if let Some(hidden_before) = note.make_notes_hidden_before {
        if let Some(threshold) = DateTime::<Utc>::from_timestamp_millis(hidden_before) {
            if note.published < threshold {
                return Ok(false);
            }
        }
    }
    // Misskey互換: make_notes_followers_only_before より前のノートはフォロワー限定扱い。
    if let Some(followers_only_before) = note.make_notes_followers_only_before {
        if let Some(threshold) = DateTime::<Utc>::from_timestamp_millis(followers_only_before) {
            if note.published < threshold {
                need_follow = true;
            }
        }
    }

    let need_mention = match note.visibility.as_str() {
        "public" | "unlisted" => false,
        "followers" => {
            need_follow = true;
            false
        }
        "direct" => true,
        _ => return Ok(false),
    };

    if need_follow {
        let followed: Option<Uuid> = sqlx::query_scalar(
            "SELECT following_id FROM followers \
             WHERE follower_id = $1 AND following_id = $2 AND accepted = true",
        )
        .bind(viewer_actor_id)
        .bind(note.actor_id)
        .fetch_optional(db)
        .await?;
        if followed.is_none() {
            return Ok(false);
        }
    }

    if need_mention {
        let viewer_ap_id: Option<String> =
            sqlx::query_scalar("SELECT ap_id FROM actors WHERE id = $1")
                .bind(viewer_actor_id)
                .fetch_optional(db)
                .await?;
        let Some(viewer_ap_id) = viewer_ap_id else {
            return Ok(false);
        };
        let mentioned = note
            .mentions
            .as_ref()
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .any(|m| m.get("ap_id").and_then(|v| v.as_str()) == Some(viewer_ap_id.as_str()))
            })
            .unwrap_or(false);
        if !mentioned {
            return Ok(false);
        }
    }

    Ok(true)
}
