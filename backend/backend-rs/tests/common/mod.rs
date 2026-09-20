use nekonoverse_backend_rs::{build_router, config::Config, db, state::AppState, valkey};

/// テスト用の `Router` を組み立てる。DATABASE_URL/VALKEY_URL は CI/ローカルの
/// テスト用 Postgres・Valkey コンテナを指す環境変数から読む
/// (`backend/tests/`(Python)の `DATABASE_URL`/`VALKEY_URL` と同じ命名)。
///
/// スキーマは Alembic が唯一の DDL 権限を持つという設計方針 (Issue #1139) に
/// 従い、Rust 側からは `alembic upgrade head` を shell out せず、呼び出し側
/// (CI のジョブステップ、あるいはローカルで手動実行するコマンド) が事前に
/// 本番と同じ経路でスキーマを構築済みであることを前提にする。
// `tests/` 配下の各ファイルは `mod common;` ごとに独立したテストバイナリとして
// コンパイルされるため、そのバイナリで使わない関数は dead_code 警告の対象に
// なる (他のテストバイナリでは使われていても検出できない)。
#[allow(dead_code)]
pub async fn test_app() -> axum::Router {
    test_app_with_db().await.0
}

/// `test_app()` に加えて、テストコードから直接シードクエリを打てるよう
/// 同じコネクションプールも返す。
pub async fn test_app_with_db() -> (axum::Router, sqlx::PgPool) {
    let config = Config::from_env();
    let db_pool = db::connect(&config)
        .await
        .expect("failed to connect to test database");
    let redis_conn = valkey::connect(&config)
        .await
        .expect("failed to connect to test valkey");
    let state = AppState {
        db: db_pool.clone(),
        redis: redis_conn,
        config,
    };
    (build_router(state), db_pool)
}
