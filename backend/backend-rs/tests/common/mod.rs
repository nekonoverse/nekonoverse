use nekonoverse_backend_rs::{build_router, config::Config, db, state::AppState, valkey};

/// テスト用の `Router` を組み立てる。DATABASE_URL/VALKEY_URL は CI/ローカルの
/// テスト用 Postgres・Valkey コンテナを指す環境変数から読む
/// (`backend/tests/`(Python)の `DATABASE_URL`/`VALKEY_URL` と同じ命名)。
///
/// 現時点 (health check のみ) では DB へのクエリは発生しないため、
/// スキーマは空のままで構わない。webfinger/nodeinfo を追加する際は、
/// ここで `alembic upgrade head` を shell out して本番と同じ経路で
/// スキーマを構築する方式に変更する (server_default 未設定カラムの
/// 取りこぼしを検出できるため)。
pub async fn test_app() -> axum::Router {
    let config = Config::from_env();
    let db_pool = db::connect(&config)
        .await
        .expect("failed to connect to test database");
    let redis_conn = valkey::connect(&config)
        .await
        .expect("failed to connect to test valkey");
    let state = AppState {
        db: db_pool,
        redis: redis_conn,
        config,
    };
    build_router(state)
}
