//! `app/services/session_service.py` のうち、ログインセッション発行に必要な
//! `create_session_with_metadata`/`record_login` のみを移植したもの。
//! 一覧/削除系 (`list_user_sessions`/`delete_session`) はまだ呼び出し元
//! (セッション管理UI) が存在しないため未移植。

use chrono::Utc;
use redis::AsyncCommands;
use sqlx::PgPool;
use uuid::Uuid;

use crate::db;
use crate::error::AppError;

/// `app.services.session_service.SESSION_TTL` と同一 (30日)。
const SESSION_TTL: u64 = 86400 * 30;

/// `app.services.session_service.create_session_with_metadata` を移植したもの。
pub async fn create_session_with_metadata(
    redis: &redis::aio::ConnectionManager,
    user_id: Uuid,
    session_id: &str,
    ip: &str,
    user_agent: Option<&str>,
) -> Result<(), AppError> {
    let mut redis = redis.clone();
    let _: () = redis
        .set_ex(
            format!("session:{session_id}"),
            user_id.to_string(),
            SESSION_TTL,
        )
        .await?;

    let meta_key = format!("session_meta:{session_id}");
    let fields: [(&str, String); 4] = [
        ("user_id", user_id.to_string()),
        ("ip", ip.to_string()),
        ("user_agent", user_agent.unwrap_or("").to_string()),
        ("created_at", Utc::now().to_rfc3339()),
    ];
    let _: () = redis.hset_multiple(&meta_key, &fields).await?;
    let _: () = redis.expire(&meta_key, SESSION_TTL as i64).await?;
    let _: () = redis
        .sadd(format!("user_sessions:{user_id}"), session_id)
        .await?;
    Ok(())
}

/// `app.services.session_service.record_login` を移植したもの
/// (`success` は常に `true` — `totp_verify` は成功時のみ呼ぶため)。
pub async fn record_login(
    db: &PgPool,
    user_id: Uuid,
    ip: &str,
    user_agent: Option<&str>,
    method: &str,
) -> Result<(), AppError> {
    sqlx::query(
        "INSERT INTO login_history (id, user_id, ip_address, user_agent, method, success, created_at) \
         VALUES ($1, $2, $3, $4, $5, true, $6)",
    )
    .bind(db::new_id())
    .bind(user_id)
    .bind(ip)
    .bind(user_agent)
    .bind(method)
    .bind(db::now())
    .execute(db)
    .await?;
    Ok(())
}
