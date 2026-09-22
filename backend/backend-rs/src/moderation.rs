//! `app/services/moderation_service.py` の `log_action` のみを移植したもの。
//! `moderation_log`テーブルは`id`/`created_at`に`server_default`が無いため
//! (`app/models/moderation_log.py`確認済み)、`db::new_id`/`db::now`で明示生成する。

use uuid::Uuid;

use crate::db;
use crate::error::AppError;
use crate::state::AppState;

/// `app.services.moderation_service.log_action` を移植したもの。
pub async fn log_action(
    state: &AppState,
    moderator_id: Uuid,
    action: &str,
    target_type: &str,
    target_id: &str,
    reason: Option<&str>,
) -> Result<(), AppError> {
    sqlx::query(
        "INSERT INTO moderation_log (id, moderator_id, action, target_type, target_id, reason, created_at) \
         VALUES ($1, $2, $3, $4, $5, $6, $7)",
    )
    .bind(db::new_id())
    .bind(moderator_id)
    .bind(action)
    .bind(target_type)
    .bind(target_id)
    .bind(reason)
    .bind(db::now())
    .execute(&state.db)
    .await?;
    Ok(())
}
