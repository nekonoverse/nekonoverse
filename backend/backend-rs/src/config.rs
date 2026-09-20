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
        }
    }

    /// `app.config.Settings.server_url` と同じ組み立て規則。
    pub fn server_url(&self) -> String {
        let scheme = if self.use_https { "https" } else { "http" };
        format!("{scheme}://{}", self.domain)
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
