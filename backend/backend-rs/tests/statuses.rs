use axum::body::Body;
use axum::http::{header, Request, StatusCode};
use chrono::Utc;
use serde_json::Value;
use tower::ServiceExt;
use uuid::Uuid;

mod common;
use common::{
    connect_redis, seed_domain_block, seed_follow, seed_local_actor, seed_note_with_visibility,
    seed_oauth_application, seed_oauth_token, seed_quote_note, seed_remote_actor, seed_renote_note,
    seed_session, seed_user,
};

async fn post(
    app: axum::Router,
    uri: &str,
    cookie: Option<&str>,
    bearer: Option<&str>,
) -> (StatusCode, Value) {
    request(app, "POST", uri, cookie, bearer).await
}

async fn get(app: axum::Router, uri: &str, cookie: Option<&str>) -> (StatusCode, Value) {
    request(app, "GET", uri, cookie, None).await
}

async fn delete_req(app: axum::Router, uri: &str, cookie: Option<&str>) -> (StatusCode, Value) {
    request(app, "DELETE", uri, cookie, None).await
}

async fn post_json(
    app: axum::Router,
    uri: &str,
    cookie: Option<&str>,
    body: Value,
) -> (StatusCode, Value) {
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

async fn request(
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

#[tokio::test]
async fn pin_own_public_note_succeeds_and_creates_pinned_row() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_user_id, actor_id, session) = seed_user_with_session(&db, &redis, "p1").await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;

    let (status, json) = post(
        app,
        &format!("/api/v1/statuses/{note_id}/pin"),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["ok"], true);

    let position: i32 = sqlx::query_scalar(
        "SELECT position FROM pinned_notes WHERE actor_id = $1 AND note_id = $2",
    )
    .bind(actor_id)
    .bind(note_id)
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(position, 0);
}

#[tokio::test]
async fn pin_and_unpin_roundtrip_delivers_add_then_remove_to_follower() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_user_id, actor_id, session) = seed_user_with_session(&db, &redis, "p2").await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;
    let domain = format!("remote-p2-{}.example", Uuid::new_v4().simple());
    let follower_id = seed_remote_actor(&db, "follower-p2", &domain).await;
    seed_follow(&db, follower_id, actor_id).await;

    let (status, _json) = post(
        app.clone(),
        &format!("/api/v1/statuses/{note_id}/pin"),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK);

    let add_row: (String, String) = sqlx::query_as(
        "SELECT target_inbox_url, payload->>'type' FROM delivery_queue \
         WHERE actor_id = $1 AND payload->>'object' = (SELECT ap_id FROM notes WHERE id = $2) \
         ORDER BY created_at DESC LIMIT 1",
    )
    .bind(actor_id)
    .bind(note_id)
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(add_row.0, format!("https://{domain}/inbox"));
    assert_eq!(add_row.1, "Add");

    let job_id: Uuid = sqlx::query_scalar(
        "SELECT id FROM delivery_queue WHERE actor_id = $1 AND payload->>'type' = 'Add' \
         ORDER BY created_at DESC LIMIT 1",
    )
    .bind(actor_id)
    .fetch_one(&db)
    .await
    .unwrap();
    let mut redis_conn = redis.clone();
    let queued: Vec<String> =
        redis::AsyncCommands::lrange(&mut redis_conn, "delivery:queue", 0, -1)
            .await
            .unwrap();
    assert!(queued.contains(&job_id.to_string()));

    let (status2, _json2) = post(
        app,
        &format!("/api/v1/statuses/{note_id}/unpin"),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status2, StatusCode::OK);

    let pinned_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM pinned_notes WHERE actor_id = $1 AND note_id = $2",
    )
    .bind(actor_id)
    .bind(note_id)
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(pinned_count, 0);

    let remove_type: String = sqlx::query_scalar(
        "SELECT payload->>'type' FROM delivery_queue WHERE actor_id = $1 \
         ORDER BY created_at DESC LIMIT 1",
    )
    .bind(actor_id)
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(remove_type, "Remove");
}

#[tokio::test]
async fn pin_up_to_max_pins_succeeds_with_sequential_positions() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_user_id, actor_id, session) = seed_user_with_session(&db, &redis, "p3").await;

    for expected_position in 0..5 {
        let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;
        let (status, _json) = post(
            app.clone(),
            &format!("/api/v1/statuses/{note_id}/pin"),
            Some(&session),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);

        let position: i32 = sqlx::query_scalar(
            "SELECT position FROM pinned_notes WHERE actor_id = $1 AND note_id = $2",
        )
        .bind(actor_id)
        .bind(note_id)
        .fetch_one(&db)
        .await
        .unwrap();
        assert_eq!(position, expected_position);
    }
}

#[tokio::test]
async fn pin_nonexistent_note_returns_422_not_404() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "p4").await;

    let (status, json) = post(
        app,
        &format!("/api/v1/statuses/{}/pin", Uuid::new_v4()),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(json["detail"], "Note not found");
}

#[tokio::test]
async fn pin_other_users_note_returns_422() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_user_a, _actor_a, session_a) = seed_user_with_session(&db, &redis, "p5a").await;
    let (_user_b, actor_b, _session_b) = seed_user_with_session(&db, &redis, "p5b").await;
    let note_id = seed_note_with_visibility(&db, actor_b, "public", Utc::now()).await;

    let (status, json) = post(
        app,
        &format!("/api/v1/statuses/{note_id}/pin"),
        Some(&session_a),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(json["detail"], "Can only pin your own notes");
}

#[tokio::test]
async fn pin_direct_note_returns_422() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_user_id, actor_id, session) = seed_user_with_session(&db, &redis, "p6").await;
    let note_id = seed_note_with_visibility(&db, actor_id, "direct", Utc::now()).await;

    let (status, json) = post(
        app,
        &format!("/api/v1/statuses/{note_id}/pin"),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(json["detail"], "Cannot pin a direct post");
}

#[tokio::test]
async fn pin_reblog_returns_422() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_user_id, actor_id, session) = seed_user_with_session(&db, &redis, "p7").await;
    let original_note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;
    let renote_id = seed_renote_note(&db, actor_id, original_note_id).await;

    let (status, json) = post(
        app,
        &format!("/api/v1/statuses/{renote_id}/pin"),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(json["detail"], "Cannot pin a reblog");
}

#[tokio::test]
async fn pin_already_pinned_returns_422() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_user_id, actor_id, session) = seed_user_with_session(&db, &redis, "p8").await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;

    let uri = format!("/api/v1/statuses/{note_id}/pin");
    let (status1, _) = post(app.clone(), &uri, Some(&session), None).await;
    assert_eq!(status1, StatusCode::OK);

    let (status2, json2) = post(app, &uri, Some(&session), None).await;
    assert_eq!(status2, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(json2["detail"], "Already pinned");
}

#[tokio::test]
async fn pin_exceeds_max_pins_returns_422() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_user_id, actor_id, session) = seed_user_with_session(&db, &redis, "p9").await;

    for _ in 0..5 {
        let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;
        let (status, _) = post(
            app.clone(),
            &format!("/api/v1/statuses/{note_id}/pin"),
            Some(&session),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
    }

    let sixth_note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;
    let (status, json) = post(
        app,
        &format!("/api/v1/statuses/{sixth_note_id}/pin"),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(json["detail"], "Maximum 5 pinned notes allowed");

    let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM pinned_notes WHERE actor_id = $1")
        .bind(actor_id)
        .fetch_one(&db)
        .await
        .unwrap();
    assert_eq!(count, 5);
}

#[tokio::test]
async fn unpin_nonexistent_note_returns_404() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_user_id, _actor_id, session) = seed_user_with_session(&db, &redis, "p10").await;

    let (status, _json) = post(
        app,
        &format!("/api/v1/statuses/{}/unpin", Uuid::new_v4()),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn unpin_not_pinned_note_returns_422() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_user_id, actor_id, session) = seed_user_with_session(&db, &redis, "p11").await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;

    let (status, json) = post(
        app,
        &format!("/api/v1/statuses/{note_id}/unpin"),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(json["detail"], "Not pinned");
}

#[tokio::test]
async fn pin_skips_delivery_to_blocked_domain_but_pin_still_succeeds() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_user_id, actor_id, session) = seed_user_with_session(&db, &redis, "p12").await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;
    let blocked_domain = format!("blocked-p12-{}.example", Uuid::new_v4().simple());
    let blocked_follower_id = seed_remote_actor(&db, "eve-p12", &blocked_domain).await;
    seed_follow(&db, blocked_follower_id, actor_id).await;
    seed_domain_block(&db, &blocked_domain).await;

    let (status, json) = post(
        app,
        &format!("/api/v1/statuses/{note_id}/pin"),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["ok"], true);

    let pinned_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM pinned_notes WHERE actor_id = $1 AND note_id = $2",
    )
    .bind(actor_id)
    .bind(note_id)
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(pinned_count, 1);

    let delivery_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM delivery_queue WHERE target_inbox_url LIKE '%' || $1 || '%'",
    )
    .bind(&blocked_domain)
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(delivery_count, 0);
}

#[tokio::test]
async fn pin_unauthenticated_returns_401() {
    let (app, _db) = common::test_app_with_db().await;
    let (status, _json) = post(
        app,
        &format!("/api/v1/statuses/{}/pin", Uuid::new_v4()),
        None,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn pin_requires_write_statuses_scope_not_bookmarks_scope() {
    let (app, db) = common::test_app_with_db().await;
    let actor_id = seed_local_actor(&db, &format!("pintest1{}", Uuid::new_v4().simple())).await;
    let user_id = seed_user(
        &db,
        actor_id,
        &format!("pin1{}@example.com", Uuid::new_v4().simple()),
    )
    .await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;

    let client_app = seed_oauth_application(&db, "write:bookmarks").await;
    let token = seed_oauth_token(&db, client_app, user_id, "write:bookmarks", None, None).await;

    let (status, json) = post(
        app,
        &format!("/api/v1/statuses/{note_id}/pin"),
        None,
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    assert!(json["detail"].as_str().unwrap().contains("write:statuses"));
}

#[tokio::test]
async fn get_status_returns_public_note_anonymously() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("getstatus1{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;

    let (status, json) = get(app, &format!("/api/v1/statuses/{note_id}"), None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["id"], note_id.to_string());
    assert_eq!(json["actor"]["username"], username);
    assert_eq!(json["reblog"], Value::Null);
    assert_eq!(json["quote"], Value::Null);
}

#[tokio::test]
async fn get_status_returns_404_for_missing_note() {
    let (app, _db) = common::test_app_with_db().await;
    let (status, json) = get(app, &format!("/api/v1/statuses/{}", Uuid::new_v4()), None).await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(json["detail"], "Note not found");
}

#[tokio::test]
async fn get_status_hides_direct_note_from_anonymous() {
    let (app, db) = common::test_app_with_db().await;
    let actor_id = seed_local_actor(&db, &format!("getstatus2{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, actor_id, "direct", Utc::now()).await;

    let (status, json) = get(app, &format!("/api/v1/statuses/{note_id}"), None).await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(json["detail"], "Note not found");
}

#[tokio::test]
async fn get_status_direct_note_visible_to_author() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_uid, actor_id, session) = seed_user_with_session(&db, &redis, "getstatus3").await;
    let note_id = seed_note_with_visibility(&db, actor_id, "direct", Utc::now()).await;

    let (status, json) = get(app, &format!("/api/v1/statuses/{note_id}"), Some(&session)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["id"], note_id.to_string());
    assert_eq!(json["visibility"], "direct");
}

#[tokio::test]
async fn get_status_hides_followers_only_note_from_non_follower() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let actor_id = seed_local_actor(&db, &format!("getstatus4{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, actor_id, "followers", Utc::now()).await;
    let (_uid, _viewer_actor, session) = seed_user_with_session(&db, &redis, "getstatus4v").await;

    let (status, json) = get(app, &format!("/api/v1/statuses/{note_id}"), Some(&session)).await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(json["detail"], "Note not found");
}

#[tokio::test]
async fn get_status_shows_followers_only_note_to_follower() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let author_id = seed_local_actor(&db, &format!("getstatus5{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, author_id, "followers", Utc::now()).await;
    let (_uid, follower_actor, session) = seed_user_with_session(&db, &redis, "getstatus5v").await;
    seed_follow(&db, follower_actor, author_id).await;

    let (status, json) = get(app, &format!("/api/v1/statuses/{note_id}"), Some(&session)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["id"], note_id.to_string());
}

#[tokio::test]
async fn get_status_renders_reblog_recursively() {
    let (app, db) = common::test_app_with_db().await;
    let original_username = format!("getstatus6orig{}", Uuid::new_v4().simple());
    let original_actor = seed_local_actor(&db, &original_username).await;
    let original_note = seed_note_with_visibility(&db, original_actor, "public", Utc::now()).await;

    let rebloggerer =
        seed_local_actor(&db, &format!("getstatus6boost{}", Uuid::new_v4().simple())).await;
    let renote_id = seed_renote_note(&db, rebloggerer, original_note).await;

    let (status, json) = get(app, &format!("/api/v1/statuses/{renote_id}"), None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["id"], renote_id.to_string());
    assert_ne!(json["reblog"], Value::Null);
    assert_eq!(json["reblog"]["id"], original_note.to_string());
    assert_eq!(json["reblog"]["actor"]["username"], original_username);
    // ネストしたreblogオブジェクト自身は常にreblogged=false/pinned=falseになる
    // (Python版の再帰呼び出しがreblogged_set/pinnedを渡さないのと同じ)。
    assert_eq!(json["reblog"]["reblogged"], false);
    assert_eq!(json["reblog"]["pinned"], false);
}

#[tokio::test]
async fn get_status_reblog_of_deleted_note_renders_null_reblog() {
    let (app, db) = common::test_app_with_db().await;
    let original_actor =
        seed_local_actor(&db, &format!("getstatus7orig{}", Uuid::new_v4().simple())).await;
    let original_note = seed_note_with_visibility(&db, original_actor, "public", Utc::now()).await;
    sqlx::query("UPDATE notes SET deleted_at = now() WHERE id = $1")
        .bind(original_note)
        .execute(&db)
        .await
        .unwrap();

    let rebloggerer =
        seed_local_actor(&db, &format!("getstatus7boost{}", Uuid::new_v4().simple())).await;
    let renote_id = seed_renote_note(&db, rebloggerer, original_note).await;

    let (status, json) = get(app, &format!("/api/v1/statuses/{renote_id}"), None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["reblog"], Value::Null);
}

#[tokio::test]
async fn get_status_renders_quote_when_target_is_visible() {
    let (app, db) = common::test_app_with_db().await;
    let quoted_username = format!("getstatus8quoted{}", Uuid::new_v4().simple());
    let quoted_actor = seed_local_actor(&db, &quoted_username).await;
    let quoted_note = seed_note_with_visibility(&db, quoted_actor, "public", Utc::now()).await;

    let quoter =
        seed_local_actor(&db, &format!("getstatus8quoter{}", Uuid::new_v4().simple())).await;
    let quote_note_id = seed_quote_note(&db, quoter, quoted_note).await;

    let (status, json) = get(app, &format!("/api/v1/statuses/{quote_note_id}"), None).await;
    assert_eq!(status, StatusCode::OK);
    assert_ne!(json["quote"], Value::Null);
    assert_eq!(json["quote"]["id"], quoted_note.to_string());
    assert_eq!(json["quote"]["actor"]["username"], quoted_username);
}

#[tokio::test]
async fn get_status_hides_quote_when_target_not_visible_to_viewer() {
    let (app, db) = common::test_app_with_db().await;
    let quoted_actor =
        seed_local_actor(&db, &format!("getstatus9quoted{}", Uuid::new_v4().simple())).await;
    let quoted_note = seed_note_with_visibility(&db, quoted_actor, "followers", Utc::now()).await;

    let quoter =
        seed_local_actor(&db, &format!("getstatus9quoter{}", Uuid::new_v4().simple())).await;
    let quote_note_id = seed_quote_note(&db, quoter, quoted_note).await;

    // quote_note_id 自体は public なので閲覧可能だが、引用先が followers-only
    // で匿名からは見えないため quote フィールドだけ null になる
    // (ステータス全体は404にならない)。
    let (status, json) = get(app, &format!("/api/v1/statuses/{quote_note_id}"), None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["id"], quote_note_id.to_string());
    assert_eq!(json["quote"], Value::Null);
}

#[tokio::test]
async fn delete_status_soft_deletes_and_delivers_to_follower() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_uid, actor_id, session) = seed_user_with_session(&db, &redis, "del1").await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;
    let domain = format!("remote-del1-{}.example", Uuid::new_v4().simple());
    let follower_id = seed_remote_actor(&db, "follower-del1", &domain).await;
    seed_follow(&db, follower_id, actor_id).await;

    let (status, _json) =
        delete_req(app, &format!("/api/v1/statuses/{note_id}"), Some(&session)).await;
    assert_eq!(status, StatusCode::NO_CONTENT);

    let deleted_at: Option<chrono::DateTime<Utc>> =
        sqlx::query_scalar("SELECT deleted_at FROM notes WHERE id = $1")
            .bind(note_id)
            .fetch_one(&db)
            .await
            .unwrap();
    assert!(deleted_at.is_some());

    let delete_row: (String, String) = sqlx::query_as(
        "SELECT target_inbox_url, payload->>'type' FROM delivery_queue \
         WHERE actor_id = $1 ORDER BY created_at DESC LIMIT 1",
    )
    .bind(actor_id)
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(delete_row.0, format!("https://{domain}/inbox"));
    assert_eq!(delete_row.1, "Delete");
}

#[tokio::test]
async fn delete_status_returns_404_for_missing_note() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_uid, _actor_id, session) = seed_user_with_session(&db, &redis, "del2").await;

    let (status, json) = delete_req(
        app,
        &format!("/api/v1/statuses/{}", Uuid::new_v4()),
        Some(&session),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(json["detail"], "Note not found");
}

#[tokio::test]
async fn delete_status_forbidden_for_other_users_note() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_uid_a, _actor_a, session_a) = seed_user_with_session(&db, &redis, "del3a").await;
    let (_uid_b, actor_b, _session_b) = seed_user_with_session(&db, &redis, "del3b").await;
    let note_id = seed_note_with_visibility(&db, actor_b, "public", Utc::now()).await;

    let (status, json) = delete_req(
        app,
        &format!("/api/v1/statuses/{note_id}"),
        Some(&session_a),
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    assert_eq!(json["detail"], "Not your note");

    let deleted_at: Option<chrono::DateTime<Utc>> =
        sqlx::query_scalar("SELECT deleted_at FROM notes WHERE id = $1")
            .bind(note_id)
            .fetch_one(&db)
            .await
            .unwrap();
    assert!(deleted_at.is_none());
}

#[tokio::test]
async fn delete_status_unauthenticated_returns_401() {
    let (app, _db) = common::test_app_with_db().await;
    let (status, _json) =
        delete_req(app, &format!("/api/v1/statuses/{}", Uuid::new_v4()), None).await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn unreblog_status_roundtrip_delivers_undo_announce() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_uid, actor_id, session) = seed_user_with_session(&db, &redis, "unre1").await;
    let original_actor =
        seed_local_actor(&db, &format!("unre1orig{}", Uuid::new_v4().simple())).await;
    let original_note = seed_note_with_visibility(&db, original_actor, "public", Utc::now()).await;
    sqlx::query("UPDATE notes SET renotes_count = 1 WHERE id = $1")
        .bind(original_note)
        .execute(&db)
        .await
        .unwrap();
    seed_renote_note(&db, actor_id, original_note).await;

    let domain = format!("remote-unre1-{}.example", Uuid::new_v4().simple());
    let follower_id = seed_remote_actor(&db, "follower-unre1", &domain).await;
    seed_follow(&db, follower_id, actor_id).await;

    let (status, json) = post(
        app,
        &format!("/api/v1/statuses/{original_note}/unreblog"),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["ok"], true);

    let renotes_count: i32 = sqlx::query_scalar("SELECT renotes_count FROM notes WHERE id = $1")
        .bind(original_note)
        .fetch_one(&db)
        .await
        .unwrap();
    assert_eq!(renotes_count, 0);

    let reblog_deleted_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM notes WHERE actor_id = $1 AND renote_of_id = $2 \
         AND deleted_at IS NOT NULL",
    )
    .bind(actor_id)
    .bind(original_note)
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(reblog_deleted_count, 1);

    let undo_row: (String, String) = sqlx::query_as(
        "SELECT target_inbox_url, payload->>'type' FROM delivery_queue \
         WHERE actor_id = $1 ORDER BY created_at DESC LIMIT 1",
    )
    .bind(actor_id)
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(undo_row.0, format!("https://{domain}/inbox"));
    assert_eq!(undo_row.1, "Undo");
}

#[tokio::test]
async fn unreblog_status_renotes_count_does_not_go_below_zero() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_uid, actor_id, session) = seed_user_with_session(&db, &redis, "unre2").await;
    let original_actor =
        seed_local_actor(&db, &format!("unre2orig{}", Uuid::new_v4().simple())).await;
    let original_note = seed_note_with_visibility(&db, original_actor, "public", Utc::now()).await;
    seed_renote_note(&db, actor_id, original_note).await;

    let (status, _json) = post(
        app,
        &format!("/api/v1/statuses/{original_note}/unreblog"),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK);

    let renotes_count: i32 = sqlx::query_scalar("SELECT renotes_count FROM notes WHERE id = $1")
        .bind(original_note)
        .fetch_one(&db)
        .await
        .unwrap();
    assert_eq!(renotes_count, 0);
}

#[tokio::test]
async fn unreblog_status_not_reblogged_returns_422() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_uid, _actor_id, session) = seed_user_with_session(&db, &redis, "unre3").await;
    let note_id = seed_note_with_visibility(
        &db,
        seed_local_actor(&db, &format!("unre3orig{}", Uuid::new_v4().simple())).await,
        "public",
        Utc::now(),
    )
    .await;

    let (status, json) = post(
        app,
        &format!("/api/v1/statuses/{note_id}/unreblog"),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(json["detail"], "Not reblogged");
}

#[tokio::test]
async fn unreblog_status_original_not_found_returns_404() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_uid, _actor_id, session) = seed_user_with_session(&db, &redis, "unre4").await;

    let (status, json) = post(
        app,
        &format!("/api/v1/statuses/{}/unreblog", Uuid::new_v4()),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(json["detail"], "Note not found");
}

#[tokio::test]
async fn unreblog_status_unauthenticated_returns_401() {
    let (app, _db) = common::test_app_with_db().await;
    let (status, _json) = post(
        app,
        &format!("/api/v1/statuses/{}/unreblog", Uuid::new_v4()),
        None,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn reblog_status_creates_note_and_delivers_announce() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_uid, actor_id, session) = seed_user_with_session(&db, &redis, "reblog1").await;
    let original_username = format!("reblog1orig{}", Uuid::new_v4().simple());
    let original_actor = seed_local_actor(&db, &original_username).await;
    let original_note = seed_note_with_visibility(&db, original_actor, "public", Utc::now()).await;
    let domain = format!("remote-reblog1-{}.example", Uuid::new_v4().simple());
    let follower_id = seed_remote_actor(&db, "follower-reblog1", &domain).await;
    seed_follow(&db, follower_id, actor_id).await;

    let (status, json) = post(
        app,
        &format!("/api/v1/statuses/{original_note}/reblog"),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_ne!(json["id"], original_note.to_string());
    assert_eq!(json["reblog"]["id"], original_note.to_string());
    assert_eq!(json["reblog"]["actor"]["username"], original_username);
    assert_eq!(json["visibility"], "public");

    let renotes_count: i32 = sqlx::query_scalar("SELECT renotes_count FROM notes WHERE id = $1")
        .bind(original_note)
        .fetch_one(&db)
        .await
        .unwrap();
    assert_eq!(renotes_count, 1);

    let announce_row: (String, String) = sqlx::query_as(
        "SELECT target_inbox_url, payload->>'type' FROM delivery_queue \
         WHERE actor_id = $1 ORDER BY created_at DESC LIMIT 1",
    )
    .bind(actor_id)
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(announce_row.0, format!("https://{domain}/inbox"));
    assert_eq!(announce_row.1, "Announce");
}

#[tokio::test]
async fn reblog_status_returns_404_for_missing_note() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_uid, _actor_id, session) = seed_user_with_session(&db, &redis, "reblog2").await;

    let (status, json) = post(
        app,
        &format!("/api/v1/statuses/{}/reblog", Uuid::new_v4()),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(json["detail"], "Note not found");
}

#[tokio::test]
async fn reblog_status_direct_post_returns_422() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_uid, actor_id, session) = seed_user_with_session(&db, &redis, "reblog3").await;
    let note_id = seed_note_with_visibility(&db, actor_id, "direct", Utc::now()).await;

    let (status, json) = post(
        app,
        &format!("/api/v1/statuses/{note_id}/reblog"),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(json["detail"], "Cannot reblog a direct post");
}

#[tokio::test]
async fn reblog_status_others_followers_post_returns_422() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_uid, actor_id, session) = seed_user_with_session(&db, &redis, "reblog4").await;
    let author = seed_local_actor(&db, &format!("reblog4author{}", Uuid::new_v4().simple())).await;
    seed_follow(&db, actor_id, author).await;
    let note_id = seed_note_with_visibility(&db, author, "followers", Utc::now()).await;

    let (status, json) = post(
        app,
        &format!("/api/v1/statuses/{note_id}/reblog"),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(json["detail"], "Cannot reblog a private post");
}

#[tokio::test]
async fn reblog_status_own_followers_post_with_wider_visibility_returns_422() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_uid, actor_id, session) = seed_user_with_session(&db, &redis, "reblog5").await;
    let note_id = seed_note_with_visibility(&db, actor_id, "followers", Utc::now()).await;

    let (status, json) = post_json(
        app,
        &format!("/api/v1/statuses/{note_id}/reblog"),
        Some(&session),
        serde_json::json!({ "visibility": "public" }),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(
        json["detail"],
        "Cannot reblog with wider visibility than the original"
    );
}

#[tokio::test]
async fn reblog_status_own_followers_post_with_default_visibility_succeeds() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_uid, actor_id, session) = seed_user_with_session(&db, &redis, "reblog6").await;
    let note_id = seed_note_with_visibility(&db, actor_id, "followers", Utc::now()).await;

    let (status, json) = post(
        app,
        &format!("/api/v1/statuses/{note_id}/reblog"),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["visibility"], "private");
}

#[tokio::test]
async fn reblog_status_private_body_visibility_maps_to_followers() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_uid, _actor_id, session) = seed_user_with_session(&db, &redis, "reblog7").await;
    let original = seed_local_actor(&db, &format!("reblog7orig{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, original, "public", Utc::now()).await;

    let (status, json) = post_json(
        app,
        &format!("/api/v1/statuses/{note_id}/reblog"),
        Some(&session),
        serde_json::json!({ "visibility": "private" }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["visibility"], "private");

    let stored_visibility: String =
        sqlx::query_scalar("SELECT visibility FROM notes WHERE id = $1")
            .bind(Uuid::parse_str(json["id"].as_str().unwrap()).unwrap())
            .fetch_one(&db)
            .await
            .unwrap();
    assert_eq!(stored_visibility, "followers");
}

#[tokio::test]
async fn reblog_status_already_reblogged_returns_422() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_uid, actor_id, session) = seed_user_with_session(&db, &redis, "reblog8").await;
    let original = seed_local_actor(&db, &format!("reblog8orig{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, original, "public", Utc::now()).await;
    seed_renote_note(&db, actor_id, note_id).await;

    let (status, json) = post(
        app,
        &format!("/api/v1/statuses/{note_id}/reblog"),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(json["detail"], "Already reblogged");
}

#[tokio::test]
async fn reblog_status_unauthenticated_returns_401() {
    let (app, _db) = common::test_app_with_db().await;
    let (status, _json) = post(
        app,
        &format!("/api/v1/statuses/{}/reblog", Uuid::new_v4()),
        None,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn reblog_status_creates_notification_for_local_author() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_uid, actor_id, session) = seed_user_with_session(&db, &redis, "reblog9").await;
    let original_actor =
        seed_local_actor(&db, &format!("reblog9orig{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, original_actor, "public", Utc::now()).await;

    let (status, _json) = post(
        app,
        &format!("/api/v1/statuses/{note_id}/reblog"),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK);

    let notif_row: (String, Uuid, Uuid) = sqlx::query_as(
        "SELECT type, recipient_id, sender_id FROM notifications \
         WHERE recipient_id = $1 ORDER BY created_at DESC LIMIT 1",
    )
    .bind(original_actor)
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(notif_row.0, "renote");
    assert_eq!(notif_row.1, original_actor);
    assert_eq!(notif_row.2, actor_id);
}

#[tokio::test]
async fn reblog_status_no_notification_for_remote_author() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_uid, _actor_id, session) = seed_user_with_session(&db, &redis, "reblog10").await;
    let domain = format!("remote-reblog10-{}.example", Uuid::new_v4().simple());
    let original_actor = seed_remote_actor(&db, "reblog10author", &domain).await;
    let note_id = seed_note_with_visibility(&db, original_actor, "public", Utc::now()).await;

    let (status, _json) = post(
        app,
        &format!("/api/v1/statuses/{note_id}/reblog"),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK);

    let notif_count: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM notifications WHERE recipient_id = $1")
            .bind(original_actor)
            .fetch_one(&db)
            .await
            .unwrap();
    assert_eq!(notif_count, 0);
}

#[tokio::test]
async fn reblog_status_no_self_notification() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_uid, actor_id, session) = seed_user_with_session(&db, &redis, "reblog11").await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;

    let (status, _json) = post(
        app,
        &format!("/api/v1/statuses/{note_id}/reblog"),
        Some(&session),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK);

    let notif_count: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM notifications WHERE recipient_id = $1")
            .bind(actor_id)
            .fetch_one(&db)
            .await
            .unwrap();
    assert_eq!(notif_count, 0);
}
