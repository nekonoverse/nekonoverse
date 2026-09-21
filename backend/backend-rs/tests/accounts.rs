use axum::body::Body;
use axum::http::{header, Request, StatusCode};
use serde_json::Value;
use tower::ServiceExt;
use uuid::Uuid;

mod common;
use common::{
    connect_redis, seed_custom_emoji, seed_follow, seed_follow_pending, seed_local_actor,
    seed_session, seed_user, seed_user_block, seed_user_mute,
};

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
        seed_local_actor(db, &format!("acctest{suffix}{}", Uuid::new_v4().simple())).await;
    let user_id = seed_user(
        db,
        actor_id,
        &format!("acc{suffix}{}@example.com", Uuid::new_v4().simple()),
    )
    .await;
    let session_id = seed_session(redis, user_id).await;
    (user_id, actor_id, session_id)
}

#[tokio::test]
async fn list_followers_returns_follower_accounts() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("followtest1{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let follower_username = format!("followerof1{}", Uuid::new_v4().simple());
    let follower_id = seed_local_actor(&db, &follower_username).await;
    seed_follow(&db, follower_id, actor_id).await;

    let (status, json) = get(app, &format!("/api/v1/accounts/{actor_id}/followers"), None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json.as_array().unwrap().len(), 1);
    assert_eq!(json[0]["username"], follower_username);
    assert_eq!(json[0]["acct"], follower_username);
    assert_eq!(json[0]["followers_count"], 0);
    assert_eq!(json[0]["statuses_count"], 0);
    assert_eq!(json[0]["last_status_at"], Value::Null);
}

#[tokio::test]
async fn list_followers_excludes_unaccepted_follow() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("followtest2{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let follower_id =
        seed_local_actor(&db, &format!("followerof2{}", Uuid::new_v4().simple())).await;
    seed_follow_pending(&db, follower_id, actor_id).await;

    let (status, json) = get(app, &format!("/api/v1/accounts/{actor_id}/followers"), None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json.as_array().unwrap().len(), 0);
}

#[tokio::test]
async fn list_followers_returns_404_for_missing_actor() {
    let (app, _db) = common::test_app_with_db().await;
    let (status, json) = get(
        app,
        &format!("/api/v1/accounts/{}/followers", Uuid::new_v4()),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(json["detail"], "Actor not found");
}

#[tokio::test]
async fn list_followers_requires_signin_when_flag_set() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let username = format!("followtest3{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    sqlx::query("UPDATE actors SET require_signin_to_view = true WHERE id = $1")
        .bind(actor_id)
        .execute(&db)
        .await
        .unwrap();
    let follower_id =
        seed_local_actor(&db, &format!("followerof3{}", Uuid::new_v4().simple())).await;
    seed_follow(&db, follower_id, actor_id).await;

    let (status, json) = get(
        app.clone(),
        &format!("/api/v1/accounts/{actor_id}/followers"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json.as_array().unwrap().len(), 0);

    let (_uid, _aid, session) = seed_user_with_session(&db, &redis, "3").await;
    let (status2, json2) = get(
        app,
        &format!("/api/v1/accounts/{actor_id}/followers"),
        Some(&session),
    )
    .await;
    assert_eq!(status2, StatusCode::OK);
    assert_eq!(json2.as_array().unwrap().len(), 1);
}

#[tokio::test]
async fn list_followers_rejects_limit_below_one() {
    let (app, db) = common::test_app_with_db().await;
    let actor_id = seed_local_actor(&db, &format!("followtest4{}", Uuid::new_v4().simple())).await;

    let (status, _json) = get(
        app,
        &format!("/api/v1/accounts/{actor_id}/followers?limit=0"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn list_followers_resolves_emojis_and_moved_account() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("followtest5{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let follower_username = format!("followerof5{}", Uuid::new_v4().simple());
    let follower_id = seed_local_actor(&db, &follower_username).await;
    seed_follow(&db, follower_id, actor_id).await;

    sqlx::query("UPDATE actors SET display_name = $1 WHERE id = $2")
        .bind(":party_cat:")
        .bind(follower_id)
        .execute(&db)
        .await
        .unwrap();
    seed_custom_emoji(
        &db,
        "party_cat",
        None,
        "https://remote.example/party_cat.png",
    )
    .await;

    let moved_to_username = format!("movedto5{}", Uuid::new_v4().simple());
    let moved_to_id = seed_local_actor(&db, &moved_to_username).await;
    let moved_to_ap_id: String = sqlx::query_scalar("SELECT ap_id FROM actors WHERE id = $1")
        .bind(moved_to_id)
        .fetch_one(&db)
        .await
        .unwrap();
    sqlx::query("UPDATE actors SET moved_to_ap_id = $1 WHERE id = $2")
        .bind(&moved_to_ap_id)
        .bind(follower_id)
        .execute(&db)
        .await
        .unwrap();

    let (status, json) = get(app, &format!("/api/v1/accounts/{actor_id}/followers"), None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json[0]["emojis"][0]["shortcode"], "party_cat");
    assert_eq!(json[0]["moved"]["username"], moved_to_username);
}

#[tokio::test]
async fn list_following_returns_followed_accounts() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("followingtest1{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let followee_username = format!("followeeof1{}", Uuid::new_v4().simple());
    let followee_id = seed_local_actor(&db, &followee_username).await;
    seed_follow(&db, actor_id, followee_id).await;

    let (status, json) = get(app, &format!("/api/v1/accounts/{actor_id}/following"), None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json.as_array().unwrap().len(), 1);
    assert_eq!(json[0]["username"], followee_username);
}

#[tokio::test]
async fn get_relationship_reports_following_and_followed_by() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_uid, actor_id, session) = seed_user_with_session(&db, &redis, "rel1").await;
    let other_id = seed_local_actor(&db, &format!("relother1{}", Uuid::new_v4().simple())).await;
    seed_follow(&db, actor_id, other_id).await;
    seed_follow(&db, other_id, actor_id).await;

    let (status, json) = get(
        app,
        &format!("/api/v1/accounts/{other_id}/relationship"),
        Some(&session),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["id"], other_id.to_string());
    assert_eq!(json["following"], true);
    assert_eq!(json["followed_by"], true);
    assert_eq!(json["requested"], false);
    assert_eq!(json["blocking"], false);
    assert_eq!(json["muting"], false);
}

#[tokio::test]
async fn get_relationship_reports_requested_for_pending_follow() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_uid, actor_id, session) = seed_user_with_session(&db, &redis, "rel2").await;
    let other_id = seed_local_actor(&db, &format!("relother2{}", Uuid::new_v4().simple())).await;
    seed_follow_pending(&db, actor_id, other_id).await;

    let (status, json) = get(
        app,
        &format!("/api/v1/accounts/{other_id}/relationship"),
        Some(&session),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["following"], false);
    assert_eq!(json["requested"], true);
}

#[tokio::test]
async fn get_relationship_reports_blocking_and_muting() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_uid, actor_id, session) = seed_user_with_session(&db, &redis, "rel3").await;
    let other_id = seed_local_actor(&db, &format!("relother3{}", Uuid::new_v4().simple())).await;
    seed_user_block(&db, actor_id, other_id).await;
    seed_user_mute(&db, actor_id, other_id, None).await;

    let (status, json) = get(
        app,
        &format!("/api/v1/accounts/{other_id}/relationship"),
        Some(&session),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["blocking"], true);
    assert_eq!(json["muting"], true);
}

#[tokio::test]
async fn get_relationship_ignores_expired_mute() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_uid, actor_id, session) = seed_user_with_session(&db, &redis, "rel4").await;
    let other_id = seed_local_actor(&db, &format!("relother4{}", Uuid::new_v4().simple())).await;
    let expired = chrono::Utc::now() - chrono::Duration::hours(1);
    seed_user_mute(&db, actor_id, other_id, Some(expired)).await;

    let (status, json) = get(
        app,
        &format!("/api/v1/accounts/{other_id}/relationship"),
        Some(&session),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["muting"], false);
}

#[tokio::test]
async fn get_relationship_requires_authentication() {
    let (app, db) = common::test_app_with_db().await;
    let other_id = seed_local_actor(&db, &format!("relother5{}", Uuid::new_v4().simple())).await;

    let (status, _json) = get(
        app,
        &format!("/api/v1/accounts/{other_id}/relationship"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn get_relationships_batch_returns_entry_per_id() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_uid, actor_id, session) = seed_user_with_session(&db, &redis, "relbatch1").await;
    let followed_id =
        seed_local_actor(&db, &format!("relbatchfollowed{}", Uuid::new_v4().simple())).await;
    let blocked_id =
        seed_local_actor(&db, &format!("relbatchblocked{}", Uuid::new_v4().simple())).await;
    seed_follow(&db, actor_id, followed_id).await;
    seed_user_block(&db, actor_id, blocked_id).await;

    let (status, json) = get(
        app,
        &format!("/api/v1/accounts/relationships?id[]={followed_id}&id[]={blocked_id}"),
        Some(&session),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let arr = json.as_array().unwrap();
    assert_eq!(arr.len(), 2);
    let followed_entry = arr
        .iter()
        .find(|e| e["id"] == followed_id.to_string())
        .unwrap();
    assert_eq!(followed_entry["following"], true);
    let blocked_entry = arr
        .iter()
        .find(|e| e["id"] == blocked_id.to_string())
        .unwrap();
    assert_eq!(blocked_entry["blocking"], true);
}

#[tokio::test]
async fn get_relationships_batch_ignores_invalid_ids_and_empty_input() {
    let (app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let (_uid, _actor_id, session) = seed_user_with_session(&db, &redis, "relbatch2").await;

    let (status, json) = get(
        app.clone(),
        "/api/v1/accounts/relationships",
        Some(&session),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json.as_array().unwrap().len(), 0);

    let (status2, json2) = get(
        app,
        "/api/v1/accounts/relationships?id[]=not-a-uuid",
        Some(&session),
    )
    .await;
    assert_eq!(status2, StatusCode::OK);
    assert_eq!(json2.as_array().unwrap().len(), 0);
}

#[tokio::test]
async fn get_relationships_batch_requires_authentication() {
    let (app, _db) = common::test_app_with_db().await;
    let (status, _json) = get(
        app,
        &format!("/api/v1/accounts/relationships?id[]={}", Uuid::new_v4()),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn list_followers_optional_auth_accepts_bearer_token() {
    // OptionalUser のベアラー経路 (認証不要エンドポイントでもトークンがあれば
    // ユーザーを解決する) が動くことだけを確認する。無効なトークンでも
    // 401にはならず、匿名として扱われることを検証する。
    let (app, db) = common::test_app_with_db().await;
    let actor_id = seed_local_actor(&db, &format!("followtest6{}", Uuid::new_v4().simple())).await;

    let request = Request::builder()
        .method("GET")
        .uri(format!("/api/v1/accounts/{actor_id}/followers"))
        .header(header::AUTHORIZATION, "Bearer invalid-token-value")
        .body(Body::empty())
        .unwrap();
    let response = app.oneshot(request).await.unwrap();
    assert_eq!(response.status(), StatusCode::OK);
}
