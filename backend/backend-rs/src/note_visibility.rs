//! `app/services/note_service.py` の単一ノート版可視性判定
//! (`check_note_visible` / 内部の `_visibility_requirements`) を移植したもの。
//!
//! 一覧APIの `filter_visible_notes`(複数ノートをまとめてフォロー確認する
//! バッチ版、ログイン済み閲覧者向け)はここでは移植しない。書き込み系
//! エンドポイント(bookmark等)が対象ノート1件だけを都度チェックする用途に
//! 限定している。ただし `get_featured` は閲覧者が常に匿名(`current_actor_id
//! = None`)であるため、`filter_visible_notes` の匿名専用の分岐だけを
//! `is_visible_to_anonymous` として切り出して移植した(フォロー確認クエリが
//! 一切不要になるため、フォロー関係を都度引く汎用バッチ版より単純)。

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

/// `app.services.note_service.filter_visible_notes` を匿名閲覧者
/// (`current_actor_id = None`) に特化して移植したもの。匿名は
/// `need_follow`/`need_mention` のどちらも満たせない(常にスキップされる)
/// ため、Python版の `_visibility_requirements` から該当分岐だけを残した:
/// `visibility` が `public`/`unlisted` であり、かつ
/// `make_notes_hidden_before`/`make_notes_followers_only_before` のいずれの
/// しきい値にも掛からないノートだけが見える。
pub fn is_visible_to_anonymous(
    visibility: &str,
    published: DateTime<Utc>,
    make_notes_hidden_before: Option<i64>,
    make_notes_followers_only_before: Option<i64>,
) -> bool {
    if !matches!(visibility, "public" | "unlisted") {
        return false;
    }
    if let Some(hidden_before) = make_notes_hidden_before {
        if let Some(threshold) = DateTime::<Utc>::from_timestamp_millis(hidden_before) {
            if published < threshold {
                return false;
            }
        }
    }
    if let Some(followers_only_before) = make_notes_followers_only_before {
        if let Some(threshold) = DateTime::<Utc>::from_timestamp_millis(followers_only_before) {
            if published < threshold {
                return false;
            }
        }
    }
    true
}

/// `app.services.note_service.check_note_visible` を、閲覧者が未認証
/// (`current_actor_id = None`) の場合も扱えるよう拡張したもの。認証済みは
/// 既存の `check_note_visible` (フォロー確認クエリを伴う) に委譲し、匿名は
/// `is_visible_to_anonymous` (クエリ不要) に委譲する。`GET /api/v1/statuses/
/// {id}` の `user: User | None = Depends(get_optional_user)` のように、
/// 閲覧者がいてもいなくても呼べるエンドポイント向け。
pub async fn check_note_visible_optional(
    db: &PgPool,
    note: &NoteVisibilityRow,
    viewer_actor_id: Option<Uuid>,
) -> Result<bool, AppError> {
    match viewer_actor_id {
        Some(id) => check_note_visible(db, note, id).await,
        None => Ok(is_visible_to_anonymous(
            &note.visibility,
            note.published,
            note.make_notes_hidden_before,
            note.make_notes_followers_only_before,
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn dt(s: &str) -> DateTime<Utc> {
        DateTime::parse_from_rfc3339(s).unwrap().with_timezone(&Utc)
    }

    #[test]
    fn anonymous_can_see_public_and_unlisted() {
        let published = dt("2026-01-01T00:00:00Z");
        assert!(is_visible_to_anonymous("public", published, None, None));
        assert!(is_visible_to_anonymous("unlisted", published, None, None));
    }

    #[test]
    fn anonymous_cannot_see_followers_or_direct() {
        let published = dt("2026-01-01T00:00:00Z");
        assert!(!is_visible_to_anonymous("followers", published, None, None));
        assert!(!is_visible_to_anonymous("direct", published, None, None));
    }

    #[test]
    fn anonymous_cannot_see_notes_hidden_before_threshold() {
        // make_notes_hidden_before はミリ秒epoch。2026-01-02T00:00:00Zより前を非表示。
        let hidden_before = dt("2026-01-02T00:00:00Z").timestamp_millis();
        let old_note = dt("2026-01-01T00:00:00Z");
        let new_note = dt("2026-01-03T00:00:00Z");
        assert!(!is_visible_to_anonymous(
            "public",
            old_note,
            Some(hidden_before),
            None
        ));
        assert!(is_visible_to_anonymous(
            "public",
            new_note,
            Some(hidden_before),
            None
        ));
    }

    #[test]
    fn anonymous_cannot_see_notes_followers_only_before_threshold() {
        let followers_only_before = dt("2026-01-02T00:00:00Z").timestamp_millis();
        let old_note = dt("2026-01-01T00:00:00Z");
        let new_note = dt("2026-01-03T00:00:00Z");
        assert!(!is_visible_to_anonymous(
            "unlisted",
            old_note,
            None,
            Some(followers_only_before)
        ));
        assert!(is_visible_to_anonymous(
            "unlisted",
            new_note,
            None,
            Some(followers_only_before)
        ));
    }
}
