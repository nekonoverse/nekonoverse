use axum::body::Body;
use axum::http::{header, Request, StatusCode};
use chrono::Utc;
use serde_json::Value;
use tower::ServiceExt;
use uuid::Uuid;

mod common;
use common::{
    connect_redis, seed_follow, seed_local_actor, seed_note_with_visibility,
    seed_oauth_application, seed_oauth_token, seed_session, seed_user,
};

async fn post(
    app: axum::Router,
    uri: &str,
    cookie: Option<&str>,
    bearer: Option<&str>,
) -> (StatusCode, Value) {
    let mut builder = Request::builder().method("POST").uri(uri);
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
        seed_local_actor(db, &format!("sttest{suffix}{}", Uuid::new_v4().simple())).await;
    let user_id = seed_user(
        db,
        actor_id,
        &format!("st{suffix}{}@example.com", Uuid::new_v4().simple()),
    )
    .await;
    let session_id = seed_session(redis, user_id).await;
    (user_id, actor_id, session_id)
}

#[tokio::test]
async fn bookmark_and_unbookmark_roundtrip() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_user_id, actor_id, session) = seed_user_with_session(&db, &redis, "1").await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;

    let (status, json) = post(
        app.clone(),
        &format!("/api/v1/statuses/{note_id}/bookmark"),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["ok"], true);

    let (status2, _json2) = post(
        app,
        &format!("/api/v1/statuses/{note_id}/unbookmark"),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status2, StatusCode::OK);
}

#[tokio::test]
async fn bookmark_not_found_returns_404() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "2").await;

    let (status, _json) = post(
        app,
        &format!("/api/v1/statuses/{}/bookmark", Uuid::new_v4()),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn bookmark_duplicate_returns_422() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_user_id, actor_id, session) = seed_user_with_session(&db, &redis, "3").await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;

    let uri = format!("/api/v1/statuses/{note_id}/bookmark");
    let (status1, _) = post(app.clone(), &uri, Some(&session), None).await;
    assert_eq!(status1, StatusCode::OK);

    let (status2, json2) = post(app, &uri, Some(&session), None).await;
    assert_eq!(status2, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(json2["detail"], "Already bookmarked");
}

#[tokio::test]
async fn unbookmark_not_found_note_returns_404() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "4").await;

    let (status, _json) = post(
        app,
        &format!("/api/v1/statuses/{}/unbookmark", Uuid::new_v4()),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn unbookmark_when_not_bookmarked_returns_422() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_user_id, actor_id, session) = seed_user_with_session(&db, &redis, "5").await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;

    let (status, json) = post(
        app,
        &format!("/api/v1/statuses/{note_id}/unbookmark"),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(json["detail"], "Not bookmarked");
}

#[tokio::test]
async fn bookmark_unauthenticated_returns_401() {
    let (app, _db) = common::test_app_with_db().await;
    let (status, _json) = post(
        app,
        &format!("/api/v1/statuses/{}/bookmark", Uuid::new_v4()),
        None,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn bookmark_invisible_followers_note_returns_404() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_user_a, _actor_a, session_a) = seed_user_with_session(&db, &redis, "6a").await;
    let (_user_b, actor_b, _session_b) = seed_user_with_session(&db, &redis, "6b").await;
    let note_id = seed_note_with_visibility(&db, actor_b, "followers", Utc::now()).await;

    let (status, _json) = post(
        app,
        &format!("/api/v1/statuses/{note_id}/bookmark"),
        Some(&session_a),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);

    let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM bookmarks WHERE note_id = $1")
        .bind(note_id)
        .fetch_one(&db)
        .await
        .unwrap();
    assert_eq!(count, 0);
}

#[tokio::test]
async fn bookmark_followers_note_as_follower_succeeds() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_user_a, actor_a, session_a) = seed_user_with_session(&db, &redis, "7a").await;
    let (_user_b, actor_b, _session_b) = seed_user_with_session(&db, &redis, "7b").await;
    seed_follow(&db, actor_a, actor_b).await;
    let note_id = seed_note_with_visibility(&db, actor_b, "followers", Utc::now()).await;

    let (status, json) = post(
        app,
        &format!("/api/v1/statuses/{note_id}/bookmark"),
        Some(&session_a),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["ok"], true);
}

#[tokio::test]
async fn bookmark_own_note_is_always_visible() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_user_id, actor_id, session) = seed_user_with_session(&db, &redis, "8").await;
    let note_id = seed_note_with_visibility(&db, actor_id, "direct", Utc::now()).await;

    let (status, _json) = post(
        app,
        &format!("/api/v1/statuses/{note_id}/bookmark"),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK);
}

#[tokio::test]
async fn bearer_write_scope_without_bookmarks_specific_scope_is_forbidden() {
    let (app, db) = common::test_app_with_db().await;
    let actor_id = seed_local_actor(&db, &format!("sctest1{}", Uuid::new_v4().simple())).await;
    let user_id = seed_user(
        &db,
        actor_id,
        &format!("sc1{}@example.com", Uuid::new_v4().simple()),
    )
    .await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;

    let client_app = seed_oauth_application(&db, "write:statuses").await;
    let token = seed_oauth_token(&db, client_app, user_id, "write:statuses", None, None).await;

    let (status, json) = post(
        app,
        &format!("/api/v1/statuses/{note_id}/bookmark"),
        None,
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    assert!(json["detail"].as_str().unwrap().contains("write:bookmarks"));
}

#[tokio::test]
async fn bearer_generic_write_scope_can_bookmark() {
    let (app, db) = common::test_app_with_db().await;
    let actor_id = seed_local_actor(&db, &format!("sctest2{}", Uuid::new_v4().simple())).await;
    let user_id = seed_user(
        &db,
        actor_id,
        &format!("sc2{}@example.com", Uuid::new_v4().simple()),
    )
    .await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;

    let client_app = seed_oauth_application(&db, "write").await;
    let token = seed_oauth_token(&db, client_app, user_id, "write", None, None).await;

    let (status, json) = post(
        app,
        &format!("/api/v1/statuses/{note_id}/bookmark"),
        None,
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["ok"], true);
}

#[tokio::test]
async fn bearer_read_only_scope_cannot_bookmark() {
    let (app, db) = common::test_app_with_db().await;
    let actor_id = seed_local_actor(&db, &format!("sctest3{}", Uuid::new_v4().simple())).await;
    let user_id = seed_user(
        &db,
        actor_id,
        &format!("sc3{}@example.com", Uuid::new_v4().simple()),
    )
    .await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;

    let client_app = seed_oauth_application(&db, "read").await;
    let token = seed_oauth_token(&db, client_app, user_id, "read", None, None).await;

    let (status, json) = post(
        app,
        &format!("/api/v1/statuses/{note_id}/bookmark"),
        None,
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    assert!(json["detail"]
        .as_str()
        .unwrap()
        .contains("write access required"));
}
