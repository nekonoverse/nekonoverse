use std::env;

/// アプリケーション設定。`app.config.Settings` (Python) の対応するフィールドと
/// 同じ環境変数名を読む。
#[derive(Clone, Debug)]
pub struct Config {
    /// sqlx がそのまま解釈できる形に正規化済みの接続文字列
    /// (`postgresql+asyncpg://` の `+asyncpg` サフィックスを除去したもの)。
    pub database_url: String,
    pub database_max_connections: u32,
    pub valkey_url: String,
    pub domain: String,
    pub use_https: bool,
    /// `app.config.Settings.registration_open` のデフォルト値。
    /// `server_settings` の `registration_mode`/`registration_open` が
    /// 未設定の場合のフォールバックとして nodeinfo から参照する。
    pub registration_open: bool,
    /// 指定時は Unix Domain Socket でこのパスに bind する (本番想定)。
    /// 未指定時は `bind_addr` で TCP bind する (開発/テスト想定)。
    pub bind_uds: Option<String>,
    pub bind_addr: String,
    /// メディアプロキシの HMAC 署名鍵導出に使う (`app.config.Settings.secret_key`)。
    pub secret_key: String,
    /// `app.config.Settings.media_proxy_key`。空文字なら `secret_key` から導出する。
    pub media_proxy_key: String,
    /// `app.config.Settings.allow_private_networks`。SSRF 保護の無効化 (連合テスト用)。
    pub allow_private_networks: bool,
    /// `app.config.Settings.media_proxy_transform_url`。media-proxy-rs (TCP) の
    /// エンドポイント。UDS (`MEDIA_PROXY_TRANSFORM_UDS`) は現状 backend-rs 側では
    /// 未対応 (別PRで追加予定) — 未設定時は変換をスキップし元画像をそのまま返す。
    pub media_proxy_transform_url: Option<String>,
    /// `app/api/mastodon/media_proxy.py` の `_TOTAL_TIMEOUT` 相当。
    /// テストで短縮できるよう環境変数から読む (本番デフォルトは30秒)。
    pub media_proxy_total_timeout_secs: u64,
}

impl Config {
    pub fn from_env() -> Self {
        let raw_database_url = env::var("DATABASE_URL").unwrap_or_else(|_| {
            "postgresql://nekonoverse:changeme@localhost:5432/nekonoverse".into()
        });

        Self {
            database_url: normalize_database_url(&raw_database_url),
            database_max_connections: env::var("RS_DB_POOL_SIZE")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(5),
            valkey_url: env::var("VALKEY_URL")
                .unwrap_or_else(|_| "redis://localhost:6379/0".into()),
            domain: env::var("DOMAIN").unwrap_or_else(|_| "localhost".into()),
            use_https: env::var("USE_HTTPS")
                .map(|v| v != "false" && v != "0")
                .unwrap_or(true),
            registration_open: env::var("REGISTRATION_OPEN")
                .map(|v| v == "true" || v == "1")
                .unwrap_or(false),
            bind_uds: env::var("BIND_UDS").ok(),
            bind_addr: env::var("BIND_ADDR").unwrap_or_else(|_| "0.0.0.0:8000".into()),
            secret_key: env::var("SECRET_KEY")
                .unwrap_or_else(|_| "change-this-to-a-random-secret-key".into()),
            media_proxy_key: env::var("MEDIA_PROXY_KEY").unwrap_or_default(),
            allow_private_networks: env::var("ALLOW_PRIVATE_NETWORKS")
                .map(|v| v == "true" || v == "1")
                .unwrap_or(false),
            media_proxy_transform_url: env::var("MEDIA_PROXY_TRANSFORM_URL")
                .ok()
                .filter(|v| !v.is_empty()),
            media_proxy_total_timeout_secs: env::var("MEDIA_PROXY_TOTAL_TIMEOUT_SECS")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(30),
        }
    }

    /// `app.config.Settings.server_url` と同じ組み立て規則。
    pub fn server_url(&self) -> String {
        let scheme = if self.use_https { "https" } else { "http" };
        format!("{scheme}://{}", self.domain)
    }

    /// `app.config.Settings.media_url` と同じ組み立て規則
    /// (`file_to_url`/`get_public_url` が返す公開URLのプレフィックス)。
    pub fn media_url(&self) -> String {
        format!("{}/media", self.server_url())
    }

    /// `app.config.Settings.media_proxy_transform_enabled` の TCP 経路相当。
    /// UDS (`MEDIA_PROXY_TRANSFORM_UDS`) は現状未対応。
    pub fn media_proxy_transform_enabled(&self) -> bool {
        self.media_proxy_transform_url.is_some()
    }
}

/// SQLAlchemy/asyncpg 方言の `postgresql+asyncpg://` を sqlx が解釈できる
/// `postgresql://` に正規化する。`?host=/var/run/postgresql` のような
/// libpq 由来のクエリパラメータ形式はそのまま sqlx でも解釈できるため変更しない。
fn normalize_database_url(url: &str) -> String {
    url.replacen("postgresql+asyncpg://", "postgresql://", 1)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalizes_asyncpg_dialect_suffix() {
        assert_eq!(
            normalize_database_url("postgresql+asyncpg://user:pass@/db?host=/var/run/postgresql"),
            "postgresql://user:pass@/db?host=/var/run/postgresql"
        );
    }

    #[test]
    fn leaves_plain_postgresql_url_unchanged() {
        assert_eq!(
            normalize_database_url("postgresql://user:pass@localhost/db"),
            "postgresql://user:pass@localhost/db"
        );
    }
}
