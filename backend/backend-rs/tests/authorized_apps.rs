use axum::body::Body;
use axum::http::{header, Request, StatusCode};
use chrono::{Duration, Utc};
use serde_json::Value;
use tower::ServiceExt;
use uuid::Uuid;

mod common;
use common::{
    connect_redis, seed_local_actor, seed_oauth_application, seed_oauth_token, seed_session,
    seed_user,
};

async fn send(
    app: axum::Router,
    method: &str,
    uri: &str,
    cookie: Option<&str>,
    bearer: Option<&str>,
) -> (StatusCode, Value) {
    let mut builder = Request::builder().method(method).uri(uri);
    if let Some(session_id) = cookie {
        builder = builder.header(header::COOKIE, format!("nekonoverse_session={session_id}"));
    }
    if let Some(token) = bearer {
        builder = builder.header(header::AUTHORIZATION, format!("Bearer {token}"));
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
        seed_local_actor(db, &format!("aatest{suffix}{}", Uuid::new_v4().simple())).await;
    let user_id = seed_user(
        db,
        actor_id,
        &format!("aa{suffix}{}@example.com", Uuid::new_v4().simple()),
    )
    .await;
    let session_id = seed_session(redis, user_id).await;
    (user_id, actor_id, session_id)
}

#[tokio::test]
async fn list_empty() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "1").await;

    let (status, json) = send(app, "GET", "/api/v1/authorized_apps", Some(&session), None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json, serde_json::json!([]));
}

#[tokio::test]
async fn list_unauthenticated_returns_401() {
    let (app, _db) = common::test_app_with_db().await;
    let (status, _json) = send(app, "GET", "/api/v1/authorized_apps", None, None).await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn list_shows_active_app() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "2").await;

    let app_id = seed_oauth_application(&db, "read write").await;
    let expires = Utc::now() + Duration::days(90);
    seed_oauth_token(&db, app_id, user_id, "read write", None, Some(expires)).await;

    let (status, json) = send(app, "GET", "/api/v1/authorized_apps", Some(&session), None).await;
    assert_eq!(status, StatusCode::OK);
    let arr = json.as_array().unwrap();
    assert_eq!(arr.len(), 1);
    assert_eq!(arr[0]["id"], app_id.to_string());
    assert_eq!(arr[0]["name"], "Test App");
    assert_eq!(arr[0]["scopes"], serde_json::json!(["read", "write"]));
    assert!(arr[0]["created_at"].as_str().unwrap().ends_with('Z'));
}

#[tokio::test]
async fn list_excludes_revoked_and_expired() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "3").await;

    let revoked_app = seed_oauth_application(&db, "read").await;
    seed_oauth_token(
        &db,
        revoked_app,
        user_id,
        "read",
        Some(Utc::now()),
        Some(Utc::now() + Duration::days(1)),
    )
    .await;

    let expired_app = seed_oauth_application(&db, "read").await;
    seed_oauth_token(
        &db,
        expired_app,
        user_id,
        "read",
        None,
        Some(Utc::now() - Duration::days(1)),
    )
    .await;

    let (status, json) = send(app, "GET", "/api/v1/authorized_apps", Some(&session), None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json, serde_json::json!([]));
}

#[tokio::test]
async fn revoke_then_list_empty() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "4").await;

    let app_id = seed_oauth_application(&db, "read write").await;
    seed_oauth_token(&db, app_id, user_id, "read write", None, None).await;

    let (status, _json) = send(
        app.clone(),
        "DELETE",
        &format!("/api/v1/authorized_apps/{app_id}"),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK);

    let (status2, json2) = send(app, "GET", "/api/v1/authorized_apps", Some(&session), None).await;
    assert_eq!(status2, StatusCode::OK);
    assert_eq!(json2, serde_json::json!([]));
}

#[tokio::test]
async fn revoke_not_found_returns_404() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "5").await;

    let (status, _json) = send(
        app,
        "DELETE",
        &format!("/api/v1/authorized_apps/{}", Uuid::new_v4()),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn revoke_does_not_affect_other_users() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (user_a, _, session_a) = seed_user_with_session(&db, &redis, "6a").await;
    let (user_b, _, _session_b) = seed_user_with_session(&db, &redis, "6b").await;

    let app_id = seed_oauth_application(&db, "read write").await;
    seed_oauth_token(&db, app_id, user_a, "read write", None, None).await;
    seed_oauth_token(&db, app_id, user_b, "read", None, None).await;

    let (status, _json) = send(
        app,
        "DELETE",
        &format!("/api/v1/authorized_apps/{app_id}"),
        Some(&session_a),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK);

    let revoked: Option<chrono::DateTime<Utc>> = sqlx::query_scalar(
        "SELECT revoked_at FROM oauth_tokens WHERE application_id = $1 AND user_id = $2",
    )
    .bind(app_id)
    .bind(user_b)
    .fetch_one(&db)
    .await
    .unwrap();
    assert!(revoked.is_none());
}

#[tokio::test]
async fn bearer_token_with_read_scope_can_list() {
    let (app, db) = common::test_app_with_db().await;
    let (user_id, _actor_id, _session) = {
        let actor_id =
            seed_local_actor(&db, &format!("bearertest1{}", Uuid::new_v4().simple())).await;
        let user_id = seed_user(
            &db,
            actor_id,
            &format!("bearer1{}@example.com", Uuid::new_v4().simple()),
        )
        .await;
        (user_id, actor_id, String::new())
    };
    let client_app_id = seed_oauth_application(&db, "read").await;
    let token = seed_oauth_token(&db, client_app_id, user_id, "read", None, None).await;

    let (status, json) = send(app, "GET", "/api/v1/authorized_apps", None, Some(&token)).await;
    assert_eq!(status, StatusCode::OK);
    // 使用したトークン自身がそのユーザーの認可済みアプリとして一覧に現れる。
    let arr = json.as_array().unwrap();
    assert_eq!(arr.len(), 1);
    assert_eq!(arr[0]["id"], client_app_id.to_string());
}

#[tokio::test]
async fn bearer_token_with_only_write_scope_cannot_list() {
    let (app, db) = common::test_app_with_db().await;
    let actor_id = seed_local_actor(&db, &format!("bearertest2{}", Uuid::new_v4().simple())).await;
    let user_id = seed_user(
        &db,
        actor_id,
        &format!("bearer2{}@example.com", Uuid::new_v4().simple()),
    )
    .await;
    let client_app_id = seed_oauth_application(&db, "write").await;
    let token = seed_oauth_token(&db, client_app_id, user_id, "write", None, None).await;

    let (status, json) = send(app, "GET", "/api/v1/authorized_apps", None, Some(&token)).await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    assert!(json["detail"]
        .as_str()
        .unwrap()
        .contains("read access required"));
}

#[tokio::test]
async fn bearer_revoked_token_returns_401() {
    let (app, db) = common::test_app_with_db().await;
    let actor_id = seed_local_actor(&db, &format!("bearertest3{}", Uuid::new_v4().simple())).await;
    let user_id = seed_user(
        &db,
        actor_id,
        &format!("bearer3{}@example.com", Uuid::new_v4().simple()),
    )
    .await;
    let client_app_id = seed_oauth_application(&db, "read").await;
    let token = seed_oauth_token(&db, client_app_id, user_id, "read", Some(Utc::now()), None).await;

    let (status, json) = send(app, "GET", "/api/v1/authorized_apps", None, Some(&token)).await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
    assert_eq!(json["detail"], "Token revoked");
}

#[tokio::test]
async fn bearer_expired_token_returns_401() {
    let (app, db) = common::test_app_with_db().await;
    let actor_id = seed_local_actor(&db, &format!("bearertest4{}", Uuid::new_v4().simple())).await;
    let user_id = seed_user(
        &db,
        actor_id,
        &format!("bearer4{}@example.com", Uuid::new_v4().simple()),
    )
    .await;
    let client_app_id = seed_oauth_application(&db, "read").await;
    let token = seed_oauth_token(
        &db,
        client_app_id,
        user_id,
        "read",
        None,
        Some(Utc::now() - Duration::days(1)),
    )
    .await;

    let (status, json) = send(app, "GET", "/api/v1/authorized_apps", None, Some(&token)).await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
    assert_eq!(json["detail"], "Token expired");
}

#[tokio::test]
async fn bearer_invalid_token_returns_401() {
    let (app, _db) = common::test_app_with_db().await;
    let (status, json) = send(
        app,
        "GET",
        "/api/v1/authorized_apps",
        None,
        Some("not-a-real-token"),
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
    assert_eq!(json["detail"], "Invalid token");
}

#[tokio::test]
async fn suspended_account_session_returns_403() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_user_id, actor_id, session) = seed_user_with_session(&db, &redis, "susp").await;
    sqlx::query("UPDATE actors SET suspended_at = now() WHERE id = $1")
        .bind(actor_id)
        .execute(&db)
        .await
        .unwrap();

    let (status, json) = send(app, "GET", "/api/v1/authorized_apps", Some(&session), None).await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    assert_eq!(json["detail"], "Account is suspended");

    // セッションは無効化されて再利用できない。
    let mut redis = redis;
    let still_exists: Option<String> =
        redis::AsyncCommands::get(&mut redis, format!("session:{session}"))
            .await
            .unwrap();
    assert!(still_exists.is_none());
}

#[tokio::test]
async fn deletion_pending_account_returns_403_with_header() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_user_id, actor_id, session) = seed_user_with_session(&db, &redis, "delpending").await;
    sqlx::query(
        "UPDATE actors SET suspended_at = now(), deletion_scheduled_at = now() + interval '7 days' WHERE id = $1",
    )
    .bind(actor_id)
    .execute(&db)
    .await
    .unwrap();

    let response = app
        .oneshot(
            Request::builder()
                .uri("/api/v1/authorized_apps")
                .header(header::COOKIE, format!("nekonoverse_session={session}"))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::FORBIDDEN);
    assert_eq!(
        response.headers().get("x-deletion-pending").unwrap(),
        "true"
    );

    // 削除猶予期間中はセッションを保持したままにする。
    let mut redis = redis;
    let still_exists: Option<String> =
        redis::AsyncCommands::get(&mut redis, format!("session:{session}"))
            .await
            .unwrap();
    assert!(still_exists.is_some());
}

#[tokio::test]
async fn pending_approval_account_returns_403() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "pending").await;
    sqlx::query("UPDATE users SET approval_status = 'pending' WHERE id = $1")
        .bind(user_id)
        .execute(&db)
        .await
        .unwrap();

    let (status, json) = send(app, "GET", "/api/v1/authorized_apps", Some(&session), None).await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    assert_eq!(json["detail"], "Your registration is pending approval");
}
