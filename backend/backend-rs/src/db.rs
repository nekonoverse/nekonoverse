use crate::config::Config;
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;

/// `app.database.py` の `create_async_engine` 相当。接続数は控えめな
/// デフォルト(5)で開始し、Python側(最大45接続)との合計が Postgres の
/// `max_connections` を圧迫しないようにする。
pub async fn connect(config: &Config) -> Result<PgPool, sqlx::Error> {
    PgPoolOptions::new()
        .max_connections(config.database_max_connections)
        .connect(&config.database_url)
        .await
}

/// `INSERT` 時に明示的に生成する必要がある id/created_at。
/// (`actors`/`users`/`notes`/`notifications` 等の中核テーブルは
/// DB 側の `server_default` を持たないため、Rust 側で必ずこのヘルパーを
/// 経由して生成すること。テーブルごとに `server_default` の有無を
/// Alembic マイグレーションで個別確認してから使うこと。)
pub fn new_id() -> uuid::Uuid {
    uuid::Uuid::new_v4()
}

pub fn now() -> chrono::DateTime<chrono::Utc> {
    chrono::Utc::now()
}
