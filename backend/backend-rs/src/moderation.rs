//! `app/services/moderation_service.py` の `log_action`、および
//! `suspend_actor`/`unsuspend_actor`/`silence_actor`/`unsilence_actor`を
//! 移植したもの。`moderation_log`テーブルは`id`/`created_at`に
//! `server_default`が無いため(`app/models/moderation_log.py`確認済み)、
//! `db::new_id`/`db::now`で明示生成する。
//!
//! `suspend_actor`/`silence_actor`等の唯一の呼び出し元(`routes/admin.rs`の
//! `/users/*`系)は常に`users`テーブルの行(=ローカル登録ユーザー)を対象に
//! するため、Python版`moderation_service.suspend_actor`が持つ
//! `if actor.is_local:`分岐は常に真として扱い、フォロワーへの
//! Delete(Person)配送とセッション無効化を無条件に行う。

use uuid::Uuid;

use crate::activitypub::render_delete_activity;
use crate::db;
use crate::delivery::enqueue_delivery;
use crate::error::AppError;
use crate::follows::get_follower_inboxes;
use crate::session::invalidate_user_sessions;
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

/// `app.services.moderation_service.suspend_actor` を移植したもの。対象の
/// 全公開ノートを論理削除し、`suspend`ログを記録した上で、対象ユーザーの
/// 全セッションを無効化してフォロワーへDelete(Person)を配送する
/// (Python版と同じ順序)。
pub async fn suspend_actor(
    state: &AppState,
    actor_id: Uuid,
    username: &str,
    user_id: Uuid,
    moderator_id: Uuid,
    reason: Option<&str>,
) -> Result<(), AppError> {
    let now = db::now();
    sqlx::query("UPDATE actors SET suspended_at = $1 WHERE id = $2")
        .bind(now)
        .bind(actor_id)
        .execute(&state.db)
        .await?;

    sqlx::query("UPDATE notes SET deleted_at = $1 WHERE actor_id = $2 AND deleted_at IS NULL")
        .bind(now)
        .bind(actor_id)
        .execute(&state.db)
        .await?;

    log_action(
        state,
        moderator_id,
        "suspend",
        "actor",
        &actor_id.to_string(),
        reason,
    )
    .await?;

    invalidate_user_sessions(&state.redis, user_id).await?;

    let actor_url = format!("{}/users/{username}", state.config.server_url());
    let delete_activity =
        render_delete_activity(&format!("{actor_url}#delete"), &actor_url, &actor_url);
    for inbox_url in get_follower_inboxes(&state.db, actor_id).await? {
        enqueue_delivery(state, actor_id, &inbox_url, &delete_activity).await?;
    }

    Ok(())
}

/// `app.services.moderation_service.unsuspend_actor` を移植したもの。
pub async fn unsuspend_actor(
    state: &AppState,
    actor_id: Uuid,
    moderator_id: Uuid,
) -> Result<(), AppError> {
    sqlx::query("UPDATE actors SET suspended_at = NULL WHERE id = $1")
        .bind(actor_id)
        .execute(&state.db)
        .await?;
    log_action(
        state,
        moderator_id,
        "unsuspend",
        "actor",
        &actor_id.to_string(),
        None,
    )
    .await
}

/// `app.services.moderation_service.silence_actor` を移植したもの。
pub async fn silence_actor(
    state: &AppState,
    actor_id: Uuid,
    moderator_id: Uuid,
    reason: Option<&str>,
) -> Result<(), AppError> {
    sqlx::query("UPDATE actors SET silenced_at = $1 WHERE id = $2")
        .bind(db::now())
        .bind(actor_id)
        .execute(&state.db)
        .await?;
    log_action(
        state,
        moderator_id,
        "silence",
        "actor",
        &actor_id.to_string(),
        reason,
    )
    .await
}

/// `app.services.moderation_service.unsilence_actor` を移植したもの。
pub async fn unsilence_actor(
    state: &AppState,
    actor_id: Uuid,
    moderator_id: Uuid,
) -> Result<(), AppError> {
    sqlx::query("UPDATE actors SET silenced_at = NULL WHERE id = $1")
        .bind(actor_id)
        .execute(&state.db)
        .await?;
    log_action(
        state,
        moderator_id,
        "unsilence",
        "actor",
        &actor_id.to_string(),
        None,
    )
    .await
}
