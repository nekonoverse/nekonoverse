use axum::body::Body;
use axum::http::{header, Request, StatusCode};
use nekonoverse_backend_rs::totp;
use serde_json::Value;
use tower::ServiceExt;
use uuid::Uuid;

mod common;
use common::{seed_custom_emoji, seed_drive_file, seed_local_actor, seed_user};

async fn get(app: axum::Router, uri: &str, cookie: Option<&str>) -> (StatusCode, Value) {
    let mut builder = Request::builder().method("GET").uri(uri);
    if let Some(session_id) = cookie {
        builder = builder.header(header::COOKIE, format!("nekonoverse_session={session_id}"));
    }
    let response = app
        .oneshot(builder.body(Body::empty()).unwrap())
        .await
        .unwrap();
    let status = response.status();
    let body = http_body_util::BodyExt::collect(response.into_body())
        .await
        .unwrap()
        .to_bytes();
    let json: Value = if body.is_empty() {
        Value::Null
    } else {
        serde_json::from_slice(&body).unwrap_or(Value::Null)
    };
    (status, json)
}

async fn post_json(
    app: axum::Router,
    uri: &str,
    cookie: Option<&str>,
    body: Value,
) -> (StatusCode, Value) {
    let (status, _headers, json) = post_json_with_headers(app, uri, cookie, body).await;
    (status, json)
}

async fn post_json_with_headers(
    app: axum::Router,
    uri: &str,
    cookie: Option<&str>,
    body: Value,
) -> (StatusCode, axum::http::HeaderMap, Value) {
    let mut builder = Request::builder()
        .method("POST")
        .uri(uri)
        .header(header::CONTENT_TYPE, "application/json");
    if let Some(session_id) = cookie {
        builder = builder.header(header::COOKIE, format!("nekonoverse_session={session_id}"));
    }
    let response = app
        .oneshot(builder.body(Body::from(body.to_string())).unwrap())
        .await
        .unwrap();
    let status = response.status();
    let headers = response.headers().clone();
    let body = http_body_util::BodyExt::collect(response.into_body())
        .await
        .unwrap()
        .to_bytes();
    let json: Value = if body.is_empty() {
        Value::Null
    } else {
        serde_json::from_slice(&body).unwrap_or(Value::Null)
    };
    (status, headers, json)
}

async fn seed_user_with_session(
    db: &sqlx::PgPool,
    redis: &redis::aio::ConnectionManager,
    suffix: &str,
) -> (Uuid, Uuid, String) {
    let actor_id =
        seed_local_actor(db, &format!("authtest{suffix}{}", Uuid::new_v4().simple())).await;
    let user_id = seed_user(
        db,
        actor_id,
        &format!("auth{suffix}{}@example.com", Uuid::new_v4().simple()),
    )
    .await;
    let session_id = common::seed_session(redis, user_id).await;
    (user_id, actor_id, session_id)
}

#[tokio::test]
async fn verify_credentials_returns_own_account() {
    let (app, db) = common::test_app_with_db().await;
    let redis = common::connect_redis().await;
    let (user_id, actor_id, session) = seed_user_with_session(&db, &redis, "1").await;

    let (status, json) = get(app, "/api/v1/accounts/verify_credentials", Some(&session)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["id"], actor_id.to_string());

    let email: String = sqlx::query_scalar("SELECT email FROM users WHERE id = $1")
        .bind(user_id)
        .fetch_one(&db)
        .await
        .unwrap();
    assert_eq!(json["email"], email);
    assert_eq!(json["source"]["privacy"], "public");
    assert_eq!(json["followers_count"], 0);
    assert_eq!(json["following_count"], 0);
    assert_eq!(json["statuses_count"], 0);
    assert_eq!(json["role"]["id"], "-1");
    assert_eq!(json["role"]["name"], "User");
    assert_eq!(json["nekonoverse_permissions"], serde_json::json!([]));
}

#[tokio::test]
async fn verify_credentials_requires_authentication() {
    let (app, _db) = common::test_app_with_db().await;
    let (status, _json) = get(app, "/api/v1/accounts/verify_credentials", None).await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn verify_credentials_admin_gets_full_moderator_permissions() {
    let (app, db) = common::test_app_with_db().await;
    let redis = common::connect_redis().await;
    let (user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "2").await;
    sqlx::query("UPDATE users SET role = 'admin' WHERE id = $1")
        .bind(user_id)
        .execute(&db)
        .await
        .unwrap();

    let (status, json) = get(app, "/api/v1/accounts/verify_credentials", Some(&session)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["role"]["id"], "3");
    assert_eq!(json["role"]["name"], "Admin");
    assert_eq!(json["role"]["highlighted"], true);
    let perms = json["nekonoverse_permissions"].as_array().unwrap();
    assert_eq!(perms.len(), 8);
    assert!(perms.iter().any(|p| p == "announcements"));
}

#[tokio::test]
async fn verify_credentials_moderator_gets_role_specific_permissions() {
    let (app, db) = common::test_app_with_db().await;
    let redis = common::connect_redis().await;
    let (user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "3").await;
    sqlx::query("UPDATE users SET role = 'moderator' WHERE id = $1")
        .bind(user_id)
        .execute(&db)
        .await
        .unwrap();

    let seeded_permissions: serde_json::Value =
        sqlx::query_scalar("SELECT permissions FROM roles WHERE name = 'moderator'")
            .fetch_one(&db)
            .await
            .unwrap();
    let expected: Vec<String> = seeded_permissions
        .as_object()
        .unwrap()
        .iter()
        .filter(|(_, v)| v.as_bool().unwrap_or(false))
        .map(|(k, _)| k.clone())
        .collect();

    let (status, json) = get(app, "/api/v1/accounts/verify_credentials", Some(&session)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["role"]["id"], "2");
    assert_eq!(json["role"]["name"], "Moderator");
    let mut perms: Vec<String> = json["nekonoverse_permissions"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap().to_string())
        .collect();
    perms.sort();
    let mut expected_sorted = expected;
    expected_sorted.sort();
    assert_eq!(perms, expected_sorted);
}

#[tokio::test]
async fn verify_credentials_includes_follow_and_status_counts() {
    let (app, db) = common::test_app_with_db().await;
    let redis = common::connect_redis().await;
    let (_user_id, actor_id, session) = seed_user_with_session(&db, &redis, "4").await;
    let follower =
        seed_local_actor(&db, &format!("authfollower4{}", Uuid::new_v4().simple())).await;
    sqlx::query(
        "INSERT INTO followers (id, follower_id, following_id, accepted, created_at) \
         VALUES ($1, $2, $3, true, now())",
    )
    .bind(Uuid::new_v4())
    .bind(follower)
    .bind(actor_id)
    .execute(&db)
    .await
    .unwrap();
    sqlx::query(
        r#"
        INSERT INTO notes (
            id, ap_id, actor_id, content, visibility, sensitive, "to", cc, published,
            replies_count, reactions_count, renotes_count, local, is_poll, poll_multiple, is_talk
        ) VALUES (
            $1, $2, $3, 'hi', 'public', false, '[]'::jsonb, '[]'::jsonb, now(),
            0, 0, 0, true, false, false, false
        )
        "#,
    )
    .bind(Uuid::new_v4())
    .bind(format!("https://localhost/notes/{}", Uuid::new_v4()))
    .bind(actor_id)
    .execute(&db)
    .await
    .unwrap();

    let (status, json) = get(app, "/api/v1/accounts/verify_credentials", Some(&session)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["followers_count"], 1);
    assert_eq!(json["statuses_count"], 1);
}

#[tokio::test]
async fn verify_credentials_resolves_display_name_emoji_and_avatar_focal() {
    let (app, db) = common::test_app_with_db().await;
    let redis = common::connect_redis().await;
    let (_user_id, actor_id, session) = seed_user_with_session(&db, &redis, "5").await;
    let shortcode = format!("blobcat{}", Uuid::new_v4().simple());
    sqlx::query("UPDATE actors SET display_name = $1 WHERE id = $2")
        .bind(format!(":{shortcode}:"))
        .bind(actor_id)
        .execute(&db)
        .await
        .unwrap();
    seed_custom_emoji(&db, &shortcode, None, "https://local.example/blobcat.png").await;

    let s3_key = format!("auth-test/{}-avatar.png", Uuid::new_v4().simple());
    let drive_file_id = seed_drive_file(&db, &s3_key, "image/png").await;
    sqlx::query("UPDATE drive_files SET focal_x = 0.5, focal_y = 0.25 WHERE id = $1")
        .bind(drive_file_id)
        .execute(&db)
        .await
        .unwrap();
    sqlx::query("UPDATE actors SET avatar_file_id = $1 WHERE id = $2")
        .bind(drive_file_id)
        .bind(actor_id)
        .execute(&db)
        .await
        .unwrap();

    let (status, json) = get(app, "/api/v1/accounts/verify_credentials", Some(&session)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["emojis"][0]["shortcode"], shortcode);
    assert_eq!(json["avatar_focal"]["x"], 0.5);
    assert_eq!(json["avatar_focal"]["y"], 0.25);
    assert_eq!(json["header_focal"], Value::Null);
}

async fn set_password(db: &sqlx::PgPool, user_id: Uuid, password: &str) {
    // `bcrypt::verify` はハッシュ自体に埋め込まれたコストで再計算するため、
    // `BCRYPT_COST`環境変数(新規ハッシュ生成のみに効く)とは無関係に、ここで
    // 最小コスト(4)を直接使ってテストの実行時間を短縮する。
    let hash = bcrypt::hash(password, 4).unwrap();
    sqlx::query("UPDATE users SET password_hash = $1 WHERE id = $2")
        .bind(hash)
        .bind(user_id)
        .execute(db)
        .await
        .unwrap();
}

#[tokio::test]
async fn totp_status_requires_authentication() {
    let (app, _db) = common::test_app_with_db().await;
    let (status, _json) = get(app, "/api/v1/auth/totp/status", None).await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn totp_status_returns_false_when_not_enabled() {
    let (app, db) = common::test_app_with_db().await;
    let redis = common::connect_redis().await;
    let (_user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "totpstatus1").await;

    let (status, json) = get(app, "/api/v1/auth/totp/status", Some(&session)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["totp_enabled"], false);
}

#[tokio::test]
async fn totp_setup_requires_authentication() {
    let (app, _db) = common::test_app_with_db().await;
    let (status, _json) = post_json(
        app,
        "/api/v1/auth/totp/setup",
        None,
        serde_json::json!({ "password": "whatever" }),
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn totp_setup_rejects_wrong_password() {
    let (app, db) = common::test_app_with_db().await;
    let redis = common::connect_redis().await;
    let (user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "totpsetup1").await;
    set_password(&db, user_id, "correct-password").await;

    let (status, json) = post_json(
        app,
        "/api/v1/auth/totp/setup",
        Some(&session),
        serde_json::json!({ "password": "wrong-password" }),
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
    assert_eq!(json["detail"], "Invalid password");
}

#[tokio::test]
async fn totp_setup_returns_secret_and_stores_encrypted_secret() {
    let (app, db) = common::test_app_with_db().await;
    let redis = common::connect_redis().await;
    let (user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "totpsetup2").await;
    set_password(&db, user_id, "correct-password").await;

    let (status, json) = post_json(
        app,
        "/api/v1/auth/totp/setup",
        Some(&session),
        serde_json::json!({ "password": "correct-password" }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let secret = json["secret"].as_str().unwrap();
    assert_eq!(secret.len(), 32);
    assert!(json["provisioning_uri"]
        .as_str()
        .unwrap()
        .starts_with("otpauth://totp/"));
    assert!(json["provisioning_uri"].as_str().unwrap().contains(secret));

    let stored: Option<String> = sqlx::query_scalar("SELECT totp_secret FROM users WHERE id = $1")
        .bind(user_id)
        .fetch_one(&db)
        .await
        .unwrap();
    assert!(stored.is_some());
    assert_ne!(stored.unwrap(), secret);
}

#[tokio::test]
async fn totp_setup_rejects_when_already_enabled() {
    let (app, db) = common::test_app_with_db().await;
    let redis = common::connect_redis().await;
    let (user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "totpsetup3").await;
    sqlx::query("UPDATE users SET totp_enabled = true WHERE id = $1")
        .bind(user_id)
        .execute(&db)
        .await
        .unwrap();

    let (status, json) = post_json(
        app,
        "/api/v1/auth/totp/setup",
        Some(&session),
        serde_json::json!({ "password": "irrelevant" }),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(json["detail"], "TOTP is already enabled");
}

async fn setup_totp(app: axum::Router, session: &str) -> String {
    let (status, json) = post_json(
        app,
        "/api/v1/auth/totp/setup",
        Some(session),
        serde_json::json!({ "password": "correct-password" }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    json["secret"].as_str().unwrap().to_string()
}

#[tokio::test]
async fn totp_enable_requires_setup_first() {
    let (app, db) = common::test_app_with_db().await;
    let redis = common::connect_redis().await;
    let (_user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "totpenable1").await;

    let (status, json) = post_json(
        app,
        "/api/v1/auth/totp/enable",
        Some(&session),
        serde_json::json!({ "code": "123456" }),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(json["detail"], "Call /auth/totp/setup first");
}

#[tokio::test]
async fn totp_enable_rejects_invalid_code() {
    let (app, db) = common::test_app_with_db().await;
    let redis = common::connect_redis().await;
    let (user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "totpenable2").await;
    set_password(&db, user_id, "correct-password").await;
    setup_totp(app.clone(), &session).await;

    let (status, json) = post_json(
        app,
        "/api/v1/auth/totp/enable",
        Some(&session),
        serde_json::json!({ "code": "000000" }),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(json["detail"], "Invalid TOTP code");
}

#[tokio::test]
async fn totp_enable_succeeds_and_returns_recovery_codes() {
    let (app, db) = common::test_app_with_db().await;
    let redis = common::connect_redis().await;
    let (user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "totpenable3").await;
    set_password(&db, user_id, "correct-password").await;
    let secret = setup_totp(app.clone(), &session).await;
    let code = totp::hotp_at(&secret, totp::current_time_step(None)).unwrap();

    let (status, json) = post_json(
        app,
        "/api/v1/auth/totp/enable",
        Some(&session),
        serde_json::json!({ "code": code }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let codes = json["recovery_codes"].as_array().unwrap();
    assert_eq!(codes.len(), 8);

    let enabled: bool = sqlx::query_scalar("SELECT totp_enabled FROM users WHERE id = $1")
        .bind(user_id)
        .fetch_one(&db)
        .await
        .unwrap();
    assert!(enabled);
}

#[tokio::test]
async fn totp_disable_requires_enabled() {
    let (app, db) = common::test_app_with_db().await;
    let redis = common::connect_redis().await;
    let (_user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "totpdisable1").await;

    let (status, json) = post_json(
        app,
        "/api/v1/auth/totp/disable",
        Some(&session),
        serde_json::json!({ "password": "whatever" }),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(json["detail"], "TOTP is not enabled");
}

#[tokio::test]
async fn totp_disable_rejects_wrong_password() {
    let (app, db) = common::test_app_with_db().await;
    let redis = common::connect_redis().await;
    let (user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "totpdisable2").await;
    set_password(&db, user_id, "correct-password").await;
    sqlx::query("UPDATE users SET totp_enabled = true WHERE id = $1")
        .bind(user_id)
        .execute(&db)
        .await
        .unwrap();

    let (status, json) = post_json(
        app,
        "/api/v1/auth/totp/disable",
        Some(&session),
        serde_json::json!({ "password": "wrong-password" }),
    )
    .await;
    // Python版はdisableのみ無効パスワードを400で返す(setupは401)。
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(json["detail"], "Invalid password");
}

#[tokio::test]
async fn totp_disable_succeeds_and_clears_fields() {
    let (app, db) = common::test_app_with_db().await;
    let redis = common::connect_redis().await;
    let (user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "totpdisable3").await;
    set_password(&db, user_id, "correct-password").await;
    let secret = setup_totp(app.clone(), &session).await;
    let code = totp::hotp_at(&secret, totp::current_time_step(None)).unwrap();
    let (status, _json) = post_json(
        app.clone(),
        "/api/v1/auth/totp/enable",
        Some(&session),
        serde_json::json!({ "code": code }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);

    let (status, json) = post_json(
        app,
        "/api/v1/auth/totp/disable",
        Some(&session),
        serde_json::json!({ "password": "correct-password" }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["ok"], true);

    let (enabled, secret_col, codes): (bool, Option<String>, Option<Value>) = sqlx::query_as(
        "SELECT totp_enabled, totp_secret, totp_recovery_codes FROM users WHERE id = $1",
    )
    .bind(user_id)
    .fetch_one(&db)
    .await
    .unwrap();
    assert!(!enabled);
    assert!(secret_col.is_none());
    assert!(codes.is_none());
}

/// `totp_verify`のテスト用に、ログイン1段階目(Python側、未移植)が発行する
/// `totp_pending:{token}`と同じ形のValkeyキーを直接シードする。
async fn seed_totp_pending(redis: &redis::aio::ConnectionManager, user_id: Uuid) -> String {
    use redis::AsyncCommands;
    let mut redis = redis.clone();
    let token = Uuid::new_v4().to_string();
    let _: () = redis
        .set_ex(format!("totp_pending:{token}"), user_id.to_string(), 300)
        .await
        .unwrap();
    token
}

async fn enable_totp_for_test(app: axum::Router, db: &sqlx::PgPool, session: &str) -> String {
    let secret = setup_totp(app.clone(), session).await;
    let code = totp::hotp_at(&secret, totp::current_time_step(None)).unwrap();
    let (status, _json) = post_json(
        app,
        "/api/v1/auth/totp/enable",
        Some(session),
        serde_json::json!({ "code": code }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let _ = db;
    secret
}

#[tokio::test]
async fn totp_verify_rejects_invalid_or_expired_token() {
    let (app, _db) = common::test_app_with_db().await;

    let (status, json) = post_json(
        app,
        "/api/v1/auth/totp/verify",
        None,
        serde_json::json!({ "totp_token": Uuid::new_v4().to_string(), "code": "123456" }),
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
    assert_eq!(json["detail"], "Invalid or expired TOTP token");
}

#[tokio::test]
async fn totp_verify_succeeds_with_valid_code_and_sets_session_cookie() {
    let (app, db) = common::test_app_with_db().await;
    let redis = common::connect_redis().await;
    let (user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "totpverify1").await;
    set_password(&db, user_id, "correct-password").await;
    let secret = enable_totp_for_test(app.clone(), &db, &session).await;
    let token = seed_totp_pending(&redis, user_id).await;

    // `enable_totp_for_test`が直前に`current_time_step(None)`のcounterを
    // 既に消費済み(`last_totp_counter`にセット)なので、同一テスト内で
    // 30秒ウィンドウをまたがずに実行できた場合は同じcounterのコードを
    // 生成してしまいリプレイ拒否されてしまう。次のcounterを明示的に使うことで
    // 実行速度に関わらず確実に未消費のコードを使う(サーバー側の±1許容
    // ウィンドウの範囲内)。
    let code = totp::hotp_at(&secret, totp::current_time_step(None) + 1).unwrap();
    let (status, headers, json) = post_json_with_headers(
        app.clone(),
        "/api/v1/auth/totp/verify",
        None,
        serde_json::json!({ "totp_token": token, "code": code }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["ok"], true);
    let set_cookie = headers.get(header::SET_COOKIE).unwrap().to_str().unwrap();
    assert!(set_cookie.starts_with("nekonoverse_session="));
    assert!(set_cookie.contains("HttpOnly"));

    // 保留トークンは使い捨てのはず。
    let (status2, _json2) = post_json(
        app,
        "/api/v1/auth/totp/verify",
        None,
        serde_json::json!({ "totp_token": token, "code": code }),
    )
    .await;
    assert_eq!(status2, StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn totp_verify_rejects_invalid_code_and_records_failure() {
    let (app, db) = common::test_app_with_db().await;
    let redis = common::connect_redis().await;
    let (user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "totpverify2").await;
    set_password(&db, user_id, "correct-password").await;
    enable_totp_for_test(app.clone(), &db, &session).await;
    let token = seed_totp_pending(&redis, user_id).await;

    let (status, json) = post_json(
        app,
        "/api/v1/auth/totp/verify",
        None,
        serde_json::json!({ "totp_token": token, "code": "000000" }),
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
    assert_eq!(json["detail"], "Invalid TOTP code");
}

#[tokio::test]
async fn totp_verify_succeeds_with_recovery_code_and_consumes_it() {
    let (app, db) = common::test_app_with_db().await;
    let redis = common::connect_redis().await;
    let (user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "totpverify3").await;
    set_password(&db, user_id, "correct-password").await;
    let secret = setup_totp(app.clone(), &session).await;
    let code = totp::hotp_at(&secret, totp::current_time_step(None)).unwrap();
    let (enable_status, enable_json) = post_json(
        app.clone(),
        "/api/v1/auth/totp/enable",
        Some(&session),
        serde_json::json!({ "code": code }),
    )
    .await;
    assert_eq!(enable_status, StatusCode::OK);
    let recovery_code = enable_json["recovery_codes"][0]
        .as_str()
        .unwrap()
        .to_string();

    let token = seed_totp_pending(&redis, user_id).await;
    let (status, json) = post_json(
        app,
        "/api/v1/auth/totp/verify",
        None,
        serde_json::json!({ "totp_token": token, "code": recovery_code }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["ok"], true);

    let remaining: Value =
        sqlx::query_scalar("SELECT totp_recovery_codes FROM users WHERE id = $1")
            .bind(user_id)
            .fetch_one(&db)
            .await
            .unwrap();
    assert_eq!(remaining.as_array().unwrap().len(), 7);
}

#[tokio::test]
async fn totp_verify_rejects_after_too_many_attempts() {
    let (app, db) = common::test_app_with_db().await;
    let redis = common::connect_redis().await;
    let (user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "totpverify4").await;
    set_password(&db, user_id, "correct-password").await;
    enable_totp_for_test(app.clone(), &db, &session).await;

    // 保留トークンは失敗時には削除されない (成功時のみ) ため、同一トークンを
    // 使い回して5回失敗させると `totp_attempts:{token}` が上限に達する。
    let token = seed_totp_pending(&redis, user_id).await;
    for _ in 0..5 {
        let (status, _json) = post_json(
            app.clone(),
            "/api/v1/auth/totp/verify",
            None,
            serde_json::json!({ "totp_token": token, "code": "000000" }),
        )
        .await;
        assert_eq!(status, StatusCode::UNAUTHORIZED);
    }

    let (status, json) = post_json(
        app,
        "/api/v1/auth/totp/verify",
        None,
        serde_json::json!({ "totp_token": token, "code": "000000" }),
    )
    .await;
    assert_eq!(status, StatusCode::TOO_MANY_REQUESTS);
    assert!(json["detail"]
        .as_str()
        .unwrap()
        .contains("Too many TOTP attempts"));
}
