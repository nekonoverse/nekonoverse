//! `app/services/domain_block_service.py` の `is_domain_blocked`、および
//! `create_domain_block`/`remove_domain_block`が書き込み時に呼ぶキャッシュ
//! 無効化(`valkey.delete(f"domain_block:{domain}")`)を移植したもの。
//! 一覧/作成/削除本体は`routes/admin.rs`側にある(配送経路の読み取り専用
//! だったこのモジュールとは責務が異なるため)。

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

/// `create_domain_block`/`remove_domain_block`が書き込み後に呼ぶ、
/// `is_domain_blocked`の`SET EX`キャッシュの無効化。
pub async fn invalidate_domain_block_cache(state: &AppState, domain: &str) -> Result<(), AppError> {
    let mut redis = state.redis.clone();
    let _: () = redis.del(format!("domain_block:{domain}")).await?;
    Ok(())
}
