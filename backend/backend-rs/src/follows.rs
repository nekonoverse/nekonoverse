//! `app/services/follow_service.py` の `get_follower_inboxes`/
//! `get_follow_counts`/`get_follower_ids` を移植したもの。

use std::collections::HashSet;

use redis::AsyncCommands;
use sqlx::PgPool;
use uuid::Uuid;

use crate::error::AppError;

#[derive(sqlx::FromRow)]
struct InboxRow {
    shared_inbox_url: Option<String>,
    inbox_url: String,
}

/// `app.services.follow_service.get_follower_inboxes` を移植したもの。
/// アクターの承認済みフォロワー全員の一意な inbox URL を返す
/// (効率のため shared inbox を優先)。
pub async fn get_follower_inboxes(db: &PgPool, actor_id: Uuid) -> Result<Vec<String>, AppError> {
    let rows: Vec<InboxRow> = sqlx::query_as(
        r#"
        SELECT a.shared_inbox_url, a.inbox_url
        FROM actors a
        JOIN followers f ON f.follower_id = a.id
        WHERE f.following_id = $1 AND f.accepted = true
        "#,
    )
    .bind(actor_id)
    .fetch_all(db)
    .await?;

    let inboxes: HashSet<String> = rows
        .into_iter()
        .map(|row| row.shared_inbox_url.unwrap_or(row.inbox_url))
        .collect();
    Ok(inboxes.into_iter().collect())
}

/// `app.services.follow_service.get_follower_ids` を移植したもの。
pub async fn get_follower_ids(db: &PgPool, actor_id: Uuid) -> Result<Vec<Uuid>, AppError> {
    let ids: Vec<Uuid> = sqlx::query_scalar(
        "SELECT follower_id FROM followers WHERE following_id = $1 AND accepted = true",
    )
    .bind(actor_id)
    .fetch_all(db)
    .await?;
    Ok(ids)
}

/// `app.services.follow_service.get_follow_counts` を移植したもの。
/// Valkey に5分間キャッシュされる。読み書きいずれのキャッシュ失敗も
/// (Python版の `try/except Exception: pass` と同じく) 無視してDB計算に
/// フォールバックする — このキャッシュは純粋な高速化目的で、Valkey障害が
/// このエンドポイント自体を落とすべきではないため。
pub async fn get_follow_counts(
    db: &PgPool,
    redis: &redis::aio::ConnectionManager,
    actor_id: Uuid,
) -> Result<(i64, i64), AppError> {
    let cache_key = format!("perf:follow_counts:{actor_id}");
    let mut conn = redis.clone();
    if let Ok(Some(cached)) = conn.get::<_, Option<String>>(&cache_key).await {
        if let Ok(parsed) = serde_json::from_str::<Vec<i64>>(&cached) {
            if let [followers, following] = parsed[..] {
                return Ok((followers, following));
            }
        }
    }

    let followers: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM followers WHERE following_id = $1 AND accepted = true",
    )
    .bind(actor_id)
    .fetch_one(db)
    .await?;
    let following: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM followers WHERE follower_id = $1 AND accepted = true",
    )
    .bind(actor_id)
    .fetch_one(db)
    .await?;

    if let Ok(payload) = serde_json::to_string(&[followers, following]) {
        let _: Result<(), _> = conn.set_ex(&cache_key, payload, 300).await;
    }

    Ok((followers, following))
}
