//! `app/services/server_settings_service.py` の `get_all_settings`/`get_setting`/
//! `set_setting`、および `app/services/push_service.py` の VAPID公開鍵導出
//! (`get_vapid_public_key_base64url`)を移植したもの。
//!
//! `get_setting`/`set_setting` は Python版と同じ Valkey キャッシュ規約
//! (`setting:{key}`, 値なしは `__NULL__` センチネル, TTL 300秒、
//! `crate::valkey::settings_cache`)に従う。`get_all_settings`はキャッシュを
//! 経由せず常にDBから直接読む(Python版の`get_all_settings`と同じ、管理画面
//! 設定一覧は最新値を見せる必要があるため)。
//!
//! VAPID秘密鍵の解決順序は Python版 `push_service._get_vapid_private_key_bytes`
//! と同じ: DB設定(`vapid_private_key`) > `VAPID_PRIVATE_KEY`環境変数 >
//! `secret_key`からHMAC-SHA256(secret_key, "vapid-private-key")で導出。
//! ただし Python版はここに「管理エンドポイントが生成した鍵をプロセス内
//! メモリにキャッシュする」層(`_cached_db_vapid_key`)を挟むが、backend-rs
//! はPython側とプロセスを分けているためこの層を持たず、常にDB(Valkey
//! キャッシュ込み)を直接見る。実際のプッシュ配送は引き続きPython側が担う
//! ため、backend-rsの`POST /admin/push/generate-vapid-key`(鍵生成・保存)は
//! 未移植のまま残す: 生成をbackend-rs側に移すとPython側プロセスの
//! `_cached_db_vapid_key`がDB更新に追従せず(起動時ロードのみ)、
//! プロセス再起動までプッシュ配送が新しい鍵と食い違う既知の問題を
//! 新たに生むため。読み取り専用のこの公開鍵導出はどちらのプロセスから
//! 行っても副作用が無く安全。

use std::collections::HashMap;

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use hmac::{Hmac, Mac};
use p256::elliptic_curve::sec1::ToEncodedPoint;
use redis::aio::ConnectionManager;
use redis::AsyncCommands;
use sha2::Sha256;
use sqlx::PgPool;

use crate::config::Config;
use crate::error::AppError;
use crate::valkey::settings_cache;

const CACHE_TTL_SECS: u64 = 300;

#[derive(sqlx::FromRow)]
struct SettingRow {
    key: String,
    value: Option<String>,
}

/// `app.services.server_settings_service.get_all_settings` を移植したもの。
pub async fn get_all_settings(db: &PgPool) -> Result<HashMap<String, Option<String>>, AppError> {
    let rows: Vec<SettingRow> = sqlx::query_as("SELECT key, value FROM server_settings")
        .fetch_all(db)
        .await?;
    Ok(rows.into_iter().map(|row| (row.key, row.value)).collect())
}

/// `app.services.server_settings_service.get_setting` を移植したもの。
pub async fn get_setting(
    db: &PgPool,
    redis: &ConnectionManager,
    key: &str,
) -> Result<Option<String>, AppError> {
    let mut conn = redis.clone();
    let cached: Option<String> = conn.get(settings_cache::cache_key(key)).await?;
    if let Some(decoded) = settings_cache::decode(cached) {
        return Ok(decoded);
    }

    let value: Option<String> =
        sqlx::query_scalar("SELECT value FROM server_settings WHERE key = $1")
            .bind(key)
            .fetch_optional(db)
            .await?
            .flatten();

    let cache_value = value
        .clone()
        .unwrap_or_else(|| settings_cache::NULL_SENTINEL.to_string());
    let _: Result<(), redis::RedisError> = conn
        .set_ex(settings_cache::cache_key(key), cache_value, CACHE_TTL_SECS)
        .await;

    Ok(value)
}

/// `app.services.server_settings_service.set_setting` を移植したもの。
pub async fn set_setting(
    db: &PgPool,
    redis: &ConnectionManager,
    key: &str,
    value: Option<&str>,
) -> Result<(), AppError> {
    sqlx::query(
        "INSERT INTO server_settings (key, value, updated_at) VALUES ($1, $2, now()) \
         ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at",
    )
    .bind(key)
    .bind(value)
    .execute(db)
    .await?;

    let mut conn = redis.clone();
    let _: Result<(), redis::RedisError> = conn.del(settings_cache::cache_key(key)).await;
    Ok(())
}

/// `app.services.push_service._get_vapid_private_key_bytes` を移植したもの
/// (プロセス内メモリキャッシュ層を除く、モジュールdocコメント参照)。
fn resolve_vapid_private_key_bytes(config: &Config, db_value: Option<&str>) -> Option<[u8; 32]> {
    if let Some(raw) = db_value.and_then(decode_raw_32) {
        return Some(raw);
    }
    if let Some(raw) = config.vapid_private_key.as_deref().and_then(decode_raw_32) {
        return Some(raw);
    }
    let mut mac = Hmac::<Sha256>::new_from_slice(config.secret_key.as_bytes())
        .expect("HMAC accepts a key of any length");
    mac.update(b"vapid-private-key");
    Some(mac.finalize().into_bytes().into())
}

fn decode_raw_32(value: &str) -> Option<[u8; 32]> {
    let bytes = URL_SAFE_NO_PAD.decode(value).ok()?;
    bytes.try_into().ok()
}

/// `app.services.push_service.get_vapid_public_key_base64url` を移植したもの。
/// 非圧縮SEC1点形式(`0x04 || X(32バイト) || Y(32バイト)`)をbase64url(パディング無し)
/// でエンコードして返す。
pub fn vapid_public_key_base64url(config: &Config, db_value: Option<&str>) -> Option<String> {
    let raw = resolve_vapid_private_key_bytes(config, db_value)?;
    let secret = p256::SecretKey::from_bytes((&raw).into()).ok()?;
    let encoded_point = secret.public_key().to_encoded_point(false);
    Some(URL_SAFE_NO_PAD.encode(encoded_point.as_bytes()))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn base_config() -> Config {
        Config {
            database_url: String::new(),
            database_max_connections: 5,
            valkey_url: String::new(),
            domain: "localhost".into(),
            use_https: true,
            registration_open: false,
            bind_uds: None,
            bind_addr: String::new(),
            secret_key: "test-secret-key".into(),
            media_proxy_key: String::new(),
            allow_private_networks: false,
            media_proxy_transform_url: None,
            media_proxy_total_timeout_secs: 30,
            bcrypt_cost: 4,
            totp_pbkdf2_iterations: 1000,
            vapid_private_key: None,
        }
    }

    /// Python版 (`cryptography`の`ec.derive_private_key`) で実際に導出した
    /// オラクル値と一致することを確認する。`secret_key`からのHMAC導出フォールバック
    /// (DB値・環境変数どちらも無い場合)の経路。
    #[test]
    fn derives_public_key_from_secret_key_matches_python_oracle() {
        let config = base_config();
        let public_key = vapid_public_key_base64url(&config, None).unwrap();
        assert_eq!(
            public_key,
            "BMUcx37uGRcKTnkmp8bqqg1fe0nOLw_akILR__eWD6VJ0YmQH9MmqNWj0eDYxMb8T4J3yBAC76PHDEfajn5dYYE"
        );
    }

    /// DB保存値(base64url, パディング無し)が優先されることを確認する。
    #[test]
    fn derives_public_key_from_db_value_matches_python_oracle() {
        let config = base_config();
        let db_value = "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA";
        let public_key = vapid_public_key_base64url(&config, Some(db_value)).unwrap();
        assert_eq!(
            public_key,
            "BFFcPW6545a5BNP-yn9U_c0MwemXvzddylFa0KbDtANfRTa-OlDzGPv5pUdZAqIhUCvvDVfgjFOyzApW8X2fk1Q"
        );
    }
}
