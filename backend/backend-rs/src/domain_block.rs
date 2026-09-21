//! `app/services/domain_block_service.py` の `is_domain_blocked` のみを
//! 移植したもの。管理画面向けのブロック作成/解除/一覧 (`create_domain_block`
//! 等) は配送経路の読み取りに不要なためこの PR のスコープ外。

use redis::AsyncCommands;

use crate::error::AppError;
use crate::state::AppState;

const CACHE_TTL_SECS: u64 = 300;

/// `app.services.domain_block_service.is_domain_blocked` を移植したもの。
pub async fn is_domain_blocked(state: &AppState, domain: &str) -> Result<bool, AppError> {
    let domain = domain.trim().to_lowercase();
    if domain.is_empty() {
        return Ok(false);
    }
    let cache_key = format!("domain_block:{domain}");

    let mut redis = state.redis.clone();
    let cached: Option<String> = redis.get(&cache_key).await?;
    if let Some(cached) = cached {
        return Ok(cached == "1");
    }

    let blocked_id: Option<uuid::Uuid> =
        sqlx::query_scalar("SELECT id FROM domain_blocks WHERE domain = $1")
            .bind(&domain)
            .fetch_optional(&state.db)
            .await?;
    let blocked = blocked_id.is_some();
    let _: () = redis
        .set_ex(&cache_key, if blocked { "1" } else { "0" }, CACHE_TTL_SECS)
        .await?;
    Ok(blocked)
}
