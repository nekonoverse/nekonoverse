use chrono::{DateTime, Utc};
use nekonoverse_backend_rs::{build_router, config::Config, db, state::AppState, valkey};
use sqlx::PgPool;
use uuid::Uuid;

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

/// `actors` テーブル (id/ap_id/username 等に `server_default` が無いため
/// 明示生成が必須) にテスト用のローカルアクターを1件投入する。
/// `backend/tests/conftest.py` の `test_user` フィクスチャに対応する最小限のシード。
#[allow(dead_code)]
pub async fn seed_local_actor(db: &PgPool, username: &str) -> Uuid {
    let id = Uuid::new_v4();
    let ap_id = format!("https://localhost/users/{username}");
    let inbox_url = format!("{ap_id}/inbox");
    sqlx::query(
        r#"
        INSERT INTO actors (
            id, ap_id, type, username, domain, inbox_url, public_key_pem,
            is_cat, manually_approves_followers, discoverable, is_bot,
            require_signin_to_view, created_at, updated_at
        ) VALUES (
            $1, $2, 'Person', $3, NULL, $4, 'dummy-pem',
            false, false, true, false,
            false, now(), now()
        )
        "#,
    )
    .bind(id)
    .bind(&ap_id)
    .bind(username)
    .bind(&inbox_url)
    .execute(db)
    .await
    .expect("failed to seed test actor");
    id
}

/// `notes` テーブルにテスト用のローカル投稿を1件投入する。
/// `backend/tests/conftest.py` の `make_note` に対応する最小限のシード。
#[allow(dead_code)]
pub async fn seed_note(db: &PgPool, actor_id: Uuid, published: DateTime<Utc>) -> Uuid {
    let id = Uuid::new_v4();
    let ap_id = format!("https://localhost/notes/{id}");
    sqlx::query(
        r#"
        INSERT INTO notes (
            id, ap_id, actor_id, content, visibility, sensitive, "to", cc, published,
            replies_count, reactions_count, renotes_count, local, is_poll, poll_multiple, is_talk
        ) VALUES (
            $1, $2, $3, 'test note', 'public', false, '[]'::jsonb, '[]'::jsonb, $4,
            0, 0, 0, true, false, false, false
        )
        "#,
    )
    .bind(id)
    .bind(&ap_id)
    .bind(actor_id)
    .bind(published)
    .execute(db)
    .await
    .expect("failed to seed test note");
    id
}
