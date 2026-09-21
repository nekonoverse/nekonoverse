use axum::body::Body;
use axum::http::{header, Request, StatusCode};
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
