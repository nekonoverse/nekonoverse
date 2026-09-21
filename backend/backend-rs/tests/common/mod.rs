use chrono::{DateTime, Utc};
use nekonoverse_backend_rs::{build_router, config::Config, db, state::AppState, valkey};
use redis::AsyncCommands;
use sha2::{Digest, Sha256};
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

/// `visibility` を指定できる `seed_note` のバリエーション。
#[allow(dead_code)]
pub async fn seed_note_with_visibility(
    db: &PgPool,
    actor_id: Uuid,
    visibility: &str,
    published: DateTime<Utc>,
) -> Uuid {
    let id = Uuid::new_v4();
    let ap_id = format!("https://localhost/notes/{id}");
    sqlx::query(
        r#"
        INSERT INTO notes (
            id, ap_id, actor_id, content, visibility, sensitive, "to", cc, published,
            replies_count, reactions_count, renotes_count, local, is_poll, poll_multiple, is_talk
        ) VALUES (
            $1, $2, $3, 'test note', $4, false, '[]'::jsonb, '[]'::jsonb, $5,
            0, 0, 0, true, false, false, false
        )
        "#,
    )
    .bind(id)
    .bind(&ap_id)
    .bind(actor_id)
    .bind(visibility)
    .bind(published)
    .execute(db)
    .await
    .expect("failed to seed test note");
    id
}

/// `users` テーブル (id/actor_id/private_key_pem 等に `server_default` が
/// 無いため明示生成が必須) にテスト用のローカルユーザーを1件投入する。
/// 事前に `seed_local_actor` で作った actor に紐付ける。
#[allow(dead_code)]
pub async fn seed_user(db: &PgPool, actor_id: Uuid, email: &str) -> Uuid {
    let id = Uuid::new_v4();
    sqlx::query(
        r#"
        INSERT INTO users (
            id, email, password_hash, actor_id, role, is_active, is_system,
            private_key_pem, approval_status, created_at
        ) VALUES (
            $1, $2, 'dummy-hash', $3, 'user', true, false,
            'dummy-pem', 'approved', now()
        )
        "#,
    )
    .bind(id)
    .bind(email)
    .bind(actor_id)
    .execute(db)
    .await
    .expect("failed to seed test user");
    id
}

/// `test_app_with_db` とは別に Valkey へ直接シードするための接続を張る。
#[allow(dead_code)]
pub async fn connect_redis() -> redis::aio::ConnectionManager {
    valkey::connect(&Config::from_env())
        .await
        .expect("failed to connect to test valkey")
}

/// `actors` テーブルにテスト用のリモートアクターを1件投入する
/// (`domain` を指定ドメインにする点が `seed_local_actor` と異なる)。
/// pin/unpin の配送先(`shared_inbox_url`)テストに使う。
#[allow(dead_code)]
pub async fn seed_remote_actor(db: &PgPool, username: &str, domain: &str) -> Uuid {
    let id = Uuid::new_v4();
    let ap_id = format!("https://{domain}/users/{username}");
    let inbox_url = format!("{ap_id}/inbox");
    let shared_inbox_url = format!("https://{domain}/inbox");
    sqlx::query(
        r#"
        INSERT INTO actors (
            id, ap_id, type, username, domain, inbox_url, shared_inbox_url, public_key_pem,
            is_cat, manually_approves_followers, discoverable, is_bot,
            require_signin_to_view, created_at, updated_at
        ) VALUES (
            $1, $2, 'Person', $3, $4, $5, $6, 'dummy-pem',
            false, false, true, false,
            false, now(), now()
        )
        "#,
    )
    .bind(id)
    .bind(&ap_id)
    .bind(username)
    .bind(domain)
    .bind(&inbox_url)
    .bind(&shared_inbox_url)
    .execute(db)
    .await
    .expect("failed to seed test remote actor");
    id
}

/// `renote_of_id` を設定した(リブログの)ノートを1件投入する。
/// pin対象としては拒否されるべきケースのテストに使う。
#[allow(dead_code)]
pub async fn seed_renote_note(db: &PgPool, actor_id: Uuid, renote_of_id: Uuid) -> Uuid {
    let id = Uuid::new_v4();
    let ap_id = format!("https://localhost/notes/{id}");
    sqlx::query(
        r#"
        INSERT INTO notes (
            id, ap_id, actor_id, content, visibility, sensitive, "to", cc, published,
            replies_count, reactions_count, renotes_count, local, is_poll, poll_multiple,
            is_talk, renote_of_id
        ) VALUES (
            $1, $2, $3, '', 'public', false, '[]'::jsonb, '[]'::jsonb, now(),
            0, 0, 0, true, false, false,
            false, $4
        )
        "#,
    )
    .bind(id)
    .bind(&ap_id)
    .bind(actor_id)
    .bind(renote_of_id)
    .execute(db)
    .await
    .expect("failed to seed test renote");
    id
}

/// `domain_blocks` にテスト用のドメインブロックを1件投入する。
#[allow(dead_code)]
pub async fn seed_domain_block(db: &PgPool, domain: &str) -> Uuid {
    let id = Uuid::new_v4();
    sqlx::query("INSERT INTO domain_blocks (id, domain) VALUES ($1, $2)")
        .bind(id)
        .bind(domain)
        .execute(db)
        .await
        .expect("failed to seed test domain block");
    id
}

/// `followers` テーブルに承認済みのフォロー関係を1件投入する。
#[allow(dead_code)]
pub async fn seed_follow(db: &PgPool, follower_id: Uuid, following_id: Uuid) -> Uuid {
    let id = Uuid::new_v4();
    sqlx::query(
        r#"
        INSERT INTO followers (id, follower_id, following_id, accepted, created_at)
        VALUES ($1, $2, $3, true, now())
        "#,
    )
    .bind(id)
    .bind(follower_id)
    .bind(following_id)
    .execute(db)
    .await
    .expect("failed to seed test follow");
    id
}

/// `followers` テーブルに未承認 (フォローリクエスト中) のフォロー関係を1件投入する。
#[allow(dead_code)]
pub async fn seed_follow_pending(db: &PgPool, follower_id: Uuid, following_id: Uuid) -> Uuid {
    let id = Uuid::new_v4();
    sqlx::query(
        r#"
        INSERT INTO followers (id, follower_id, following_id, accepted, created_at)
        VALUES ($1, $2, $3, false, now())
        "#,
    )
    .bind(id)
    .bind(follower_id)
    .bind(following_id)
    .execute(db)
    .await
    .expect("failed to seed test pending follow");
    id
}

/// `user_blocks` にテスト用のブロックを1件投入する。
#[allow(dead_code)]
pub async fn seed_user_block(db: &PgPool, actor_id: Uuid, target_id: Uuid) -> Uuid {
    let id = Uuid::new_v4();
    sqlx::query(
        "INSERT INTO user_blocks (id, actor_id, target_id, created_at) VALUES ($1, $2, $3, now())",
    )
    .bind(id)
    .bind(actor_id)
    .bind(target_id)
    .execute(db)
    .await
    .expect("failed to seed test user block");
    id
}

/// `user_mutes` にテスト用のミュートを1件投入する。`expires_at` は任意。
#[allow(dead_code)]
pub async fn seed_user_mute(
    db: &PgPool,
    actor_id: Uuid,
    target_id: Uuid,
    expires_at: Option<DateTime<Utc>>,
) -> Uuid {
    let id = Uuid::new_v4();
    sqlx::query(
        "INSERT INTO user_mutes (id, actor_id, target_id, expires_at, created_at) \
         VALUES ($1, $2, $3, $4, now())",
    )
    .bind(id)
    .bind(actor_id)
    .bind(target_id)
    .bind(expires_at)
    .execute(db)
    .await
    .expect("failed to seed test user mute");
    id
}

/// `custom_emojis` にテスト用の絵文字を1件投入する。`domain` が `None` ならローカル。
#[allow(dead_code)]
pub async fn seed_custom_emoji(
    db: &PgPool,
    shortcode: &str,
    domain: Option<&str>,
    url: &str,
) -> Uuid {
    let id = Uuid::new_v4();
    sqlx::query(
        "INSERT INTO custom_emojis (id, shortcode, domain, url, visible_in_picker) \
         VALUES ($1, $2, $3, $4, true)",
    )
    .bind(id)
    .bind(shortcode)
    .bind(domain)
    .bind(url)
    .execute(db)
    .await
    .expect("failed to seed test custom emoji");
    id
}

/// `pinned_notes` にテスト用のピン留めを1件投入する。
#[allow(dead_code)]
pub async fn seed_pinned_note(db: &PgPool, actor_id: Uuid, note_id: Uuid, position: i32) -> Uuid {
    let id = Uuid::new_v4();
    sqlx::query(
        "INSERT INTO pinned_notes (id, actor_id, note_id, position, created_at) \
         VALUES ($1, $2, $3, $4, now())",
    )
    .bind(id)
    .bind(actor_id)
    .bind(note_id)
    .bind(position)
    .execute(db)
    .await
    .expect("failed to seed test pinned note");
    id
}

/// `drive_files` にテスト用のファイルを1件投入する。
/// get_outbox/get_featured の添付ファイルレンダリングのテストに使う。
#[allow(dead_code)]
pub async fn seed_drive_file(db: &PgPool, s3_key: &str, mime_type: &str) -> Uuid {
    let id = Uuid::new_v4();
    sqlx::query(
        r#"
        INSERT INTO drive_files (
            id, s3_key, filename, mime_type, size_bytes, server_file, created_at
        ) VALUES ($1, $2, 'test.bin', $3, 1024, false, now())
        "#,
    )
    .bind(id)
    .bind(s3_key)
    .bind(mime_type)
    .execute(db)
    .await
    .expect("failed to seed test drive file");
    id
}

/// `note_attachments` に drive_file 参照の添付を1件投入する。
#[allow(dead_code)]
pub async fn seed_note_attachment(
    db: &PgPool,
    note_id: Uuid,
    drive_file_id: Uuid,
    position: i32,
) -> Uuid {
    let id = Uuid::new_v4();
    sqlx::query(
        "INSERT INTO note_attachments (id, note_id, drive_file_id, position) \
         VALUES ($1, $2, $3, $4)",
    )
    .bind(id)
    .bind(note_id)
    .bind(drive_file_id)
    .bind(position)
    .execute(db)
    .await
    .expect("failed to seed test note attachment");
    id
}

/// `note_attachments` にファイルをダウンロードしない remote 添付を1件投入する。
#[allow(dead_code)]
pub async fn seed_remote_note_attachment(
    db: &PgPool,
    note_id: Uuid,
    remote_url: &str,
    remote_mime_type: &str,
    position: i32,
) -> Uuid {
    let id = Uuid::new_v4();
    sqlx::query(
        "INSERT INTO note_attachments (id, note_id, remote_url, remote_mime_type, position) \
         VALUES ($1, $2, $3, $4, $5)",
    )
    .bind(id)
    .bind(note_id)
    .bind(remote_url)
    .bind(remote_mime_type)
    .bind(position)
    .execute(db)
    .await
    .expect("failed to seed test remote note attachment");
    id
}

/// Valkey に `session:{id}` -> user_id のセッションを1件投入し、
/// axum テストリクエストの `Cookie` ヘッダーにそのまま使えるセッションIDを返す。
#[allow(dead_code)]
pub async fn seed_session(redis: &redis::aio::ConnectionManager, user_id: Uuid) -> String {
    let mut conn = redis.clone();
    let session_id = Uuid::new_v4().to_string();
    let _: () = conn
        .set(format!("session:{session_id}"), user_id.to_string())
        .await
        .expect("failed to seed test session");
    session_id
}

/// `oauth_applications` にテスト用アプリを1件投入する。
#[allow(dead_code)]
pub async fn seed_oauth_application(db: &PgPool, scopes: &str) -> Uuid {
    let id = Uuid::new_v4();
    sqlx::query(
        r#"
        INSERT INTO oauth_applications (
            id, name, client_id, client_secret, redirect_uris, scopes, created_at
        ) VALUES ($1, 'Test App', $2, 'secret', 'http://localhost/callback', $3, now())
        "#,
    )
    .bind(id)
    .bind(format!("client-{id}"))
    .bind(scopes)
    .execute(db)
    .await
    .expect("failed to seed test oauth application");
    id
}

/// `oauth_tokens` にテスト用トークンを1件投入し、平文トークン (Authorization
/// ヘッダーにそのまま使える値) を返す。`access_token` 列にはハッシュ化した
/// 値を保存する (`app.dependencies.get_oauth_user` の新方式と同じ)。
#[allow(dead_code)]
pub async fn seed_oauth_token(
    db: &PgPool,
    application_id: Uuid,
    user_id: Uuid,
    scopes: &str,
    revoked_at: Option<DateTime<Utc>>,
    expires_at: Option<DateTime<Utc>>,
) -> String {
    let plain_token = Uuid::new_v4().to_string();
    let token_hash = format!("{:x}", Sha256::digest(plain_token.as_bytes()));
    sqlx::query(
        r#"
        INSERT INTO oauth_tokens (
            id, access_token, token_type, scopes, application_id, user_id,
            created_at, expires_at, revoked_at
        ) VALUES ($1, $2, 'Bearer', $3, $4, $5, now(), $6, $7)
        "#,
    )
    .bind(Uuid::new_v4())
    .bind(&token_hash)
    .bind(scopes)
    .bind(application_id)
    .bind(user_id)
    .bind(expires_at)
    .bind(revoked_at)
    .execute(db)
    .await
    .expect("failed to seed test oauth token");
    plain_token
}

/// `reactions` にテスト用のリアクションを1件投入する。
#[allow(dead_code)]
pub async fn seed_reaction(db: &PgPool, note_id: Uuid, actor_id: Uuid, emoji: &str) -> Uuid {
    let id = Uuid::new_v4();
    sqlx::query(
        "INSERT INTO reactions (id, actor_id, note_id, emoji, created_at) \
         VALUES ($1, $2, $3, $4, now())",
    )
    .bind(id)
    .bind(actor_id)
    .bind(note_id)
    .bind(emoji)
    .execute(db)
    .await
    .expect("failed to seed test reaction");
    id
}

/// `hashtags`/`note_hashtags` にテスト用のハッシュタグ紐付けを1件投入する。
#[allow(dead_code)]
pub async fn seed_hashtag_for_note(db: &PgPool, note_id: Uuid, name: &str) -> Uuid {
    let hashtag_id: Uuid =
        sqlx::query_scalar("INSERT INTO hashtags (name) VALUES ($1) RETURNING id")
            .bind(name)
            .fetch_one(db)
            .await
            .expect("failed to seed test hashtag");
    sqlx::query("INSERT INTO note_hashtags (note_id, hashtag_id) VALUES ($1, $2)")
        .bind(note_id)
        .bind(hashtag_id)
        .execute(db)
        .await
        .expect("failed to seed test note_hashtag");
    hashtag_id
}

/// `preview_cards` にテスト用のプレビューカードを1件投入する。
#[allow(dead_code)]
pub async fn seed_preview_card(db: &PgPool, note_id: Uuid, url: &str, title: &str) -> Uuid {
    let id = Uuid::new_v4();
    sqlx::query(
        "INSERT INTO preview_cards (id, note_id, url, title, card_type, created_at) \
         VALUES ($1, $2, $3, $4, 'link', now())",
    )
    .bind(id)
    .bind(note_id)
    .bind(url)
    .bind(title)
    .execute(db)
    .await
    .expect("failed to seed test preview card");
    id
}

/// `poll_votes` にテスト用の投票を1件投入する。
#[allow(dead_code)]
pub async fn seed_poll_vote(db: &PgPool, note_id: Uuid, actor_id: Uuid, choice_index: i32) -> Uuid {
    let id = Uuid::new_v4();
    sqlx::query(
        "INSERT INTO poll_votes (id, note_id, actor_id, choice_index, created_at) \
         VALUES ($1, $2, $3, $4, now())",
    )
    .bind(id)
    .bind(note_id)
    .bind(actor_id)
    .bind(choice_index)
    .execute(db)
    .await
    .expect("failed to seed test poll vote");
    id
}
