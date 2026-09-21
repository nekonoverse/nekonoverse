//! `app/services/follow_service.py` の `get_follower_inboxes` のみを
//! 移植したもの。

use std::collections::HashSet;

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
