//! `app/services/delivery_service.py` の `enqueue_delivery` (単発配送) の
//! みを移植したもの。バッチ版 `enqueue_deliveries` は呼び出し元がまだ
//! 無いため未移植。HTTP Signature 検証・実際のHTTP配送(delivery worker)は
//! 引き続きPython側が担当し、ここでは配送キューへの投入(プロデューサ)
//! のみを行う。

use redis::AsyncCommands;
use reqwest::Url;
use sqlx::types::Json;
use uuid::Uuid;

use crate::db;
use crate::domain_block::is_domain_blocked;
use crate::error::AppError;
use crate::state::AppState;

/// `app.services.delivery_service.enqueue_delivery` を移植したもの。
/// ブロック中ドメインへは何もせず(ログのみ)正常終了する
/// (Python版が `None` を返すのと同じ扱い、呼び出し元は戻り値を見ない)。
pub async fn enqueue_delivery(
    state: &AppState,
    actor_id: Uuid,
    target_inbox_url: &str,
    payload: &serde_json::Value,
) -> Result<(), AppError> {
    let domain = Url::parse(target_inbox_url)
        .ok()
        .and_then(|u| u.host_str().map(str::to_string));

    if let Some(domain) = &domain {
        if is_domain_blocked(state, domain).await? {
            tracing::info!(domain = %domain, "Skipping delivery to blocked domain");
            return Ok(());
        }
    }

    let job_id = db::new_id();
    sqlx::query(
        r#"
        INSERT INTO delivery_queue (id, actor_id, target_inbox_url, payload, status, created_at)
        VALUES ($1, $2, $3, $4, 'pending', $5)
        "#,
    )
    .bind(job_id)
    .bind(actor_id)
    .bind(target_inbox_url)
    .bind(Json(payload))
    .bind(db::now())
    .execute(&state.db)
    .await?;

    let mut redis = state.redis.clone();
    let _: () = redis.lpush("delivery:queue", job_id.to_string()).await?;

    Ok(())
}
