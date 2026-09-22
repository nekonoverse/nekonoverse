//! `app/services/session_service.py` のうち、ログインセッション発行に必要な
//! `create_session_with_metadata`/`record_login`、および
//! `app.services.moderation_service.invalidate_user_sessions`
//! (`cleanup_session_metadata`込み)を移植したもの。一覧系
//! (`list_user_sessions`)、`exclude_session`付きの`delete_session`/
//! ログアウト経路の`invalidate_user_sessions`呼び出しはまだ呼び出し元
//! (セッション管理UI、`auth.py`のログアウト全端末)が存在しないため未移植。

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

/// `app.services.session_service.cleanup_session_metadata` を移植したもの。
async fn cleanup_session_metadata(
    redis: &mut redis::aio::ConnectionManager,
    user_id: Uuid,
    session_id: &str,
) -> Result<(), AppError> {
    let _: () = redis.del(format!("session_meta:{session_id}")).await?;
    let _: () = redis
        .srem(format!("user_sessions:{user_id}"), session_id)
        .await?;
    Ok(())
}

/// `app.services.moderation_service.invalidate_user_sessions` を移植したもの
/// (`exclude_session`引数は現時点の呼び出し元(`suspend_actor`)が使わないため
/// 省略)。`session:*`キーをSCANし、値が`user_id`に一致するものを削除する。
pub async fn invalidate_user_sessions(
    redis: &redis::aio::ConnectionManager,
    user_id: Uuid,
) -> Result<(), AppError> {
    let mut redis = redis.clone();
    let user_id_str = user_id.to_string();
    let mut cursor: u64 = 0;
    loop {
        let (next_cursor, keys): (u64, Vec<String>) = redis::cmd("SCAN")
            .arg(cursor)
            .arg("MATCH")
            .arg("session:*")
            .arg("COUNT")
            .arg(100)
            .query_async(&mut redis)
            .await?;
        for key in &keys {
            let value: Option<String> = redis.get(key).await?;
            if value.as_deref() == Some(user_id_str.as_str()) {
                let session_id = key.trim_start_matches("session:");
                let _: () = redis.del(key).await?;
                cleanup_session_metadata(&mut redis, user_id, session_id).await?;
            }
        }
        cursor = next_cursor;
        if cursor == 0 {
            break;
        }
    }
    let _: () = redis.del(format!("user_sessions:{user_id}")).await?;
    Ok(())
}
