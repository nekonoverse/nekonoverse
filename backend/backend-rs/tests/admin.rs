//! `routes/admin.rs`(domain_blocks/reports/notes moderation/log系)と
//! `admin_auth::require_permission`/`require_moderation_staff`の結合テスト。
//! `app/dependencies.get_permitted_staff("domains"|"reports"|"content")`と
//! 同じ権限判定(admin role即許可・非staffは拒否・カスタムroleは
//! permissions JSONB次第)、`get_moderation_staff`(モデレーター権限を
//! 何か1つでも持てば許可)、およびOAuthトークン経由での
//! `admin:read`/`admin:write`スコープ要求(`_require_admin_scope`)を検証する。

use axum::body::Body;
use axum::http::{Request, StatusCode};
use chrono::Utc;
use redis::AsyncCommands;
use serde_json::{json, Value};
use sqlx::PgPool;
use tower::ServiceExt;
use uuid::Uuid;

mod common;
use common::{
    seed_delivery_job, seed_follow, seed_local_actor, seed_note_with_visibility,
    seed_oauth_application, seed_oauth_token, seed_remote_actor, seed_report, seed_session,
    seed_user, test_app_with_db,
};

async fn body_json(response: axum::response::Response<Body>) -> Value {
    let body = http_body_util::BodyExt::collect(response.into_body())
        .await
        .unwrap()
        .to_bytes();
    if body.is_empty() {
        Value::Null
    } else {
        serde_json::from_slice(&body).unwrap_or(Value::Null)
    }
}

async fn set_user_role(db: &PgPool, user_id: Uuid, role: &str) {
    sqlx::query("UPDATE users SET role = $1 WHERE id = $2")
        .bind(role)
        .bind(user_id)
        .execute(db)
        .await
        .unwrap();
}

async fn set_user_is_system(db: &PgPool, user_id: Uuid) {
    sqlx::query("UPDATE users SET is_system = true WHERE id = $1")
        .bind(user_id)
        .execute(db)
        .await
        .unwrap();
}

async fn seed_role(db: &PgPool, name: &str, is_admin: bool, permissions: Value) {
    sqlx::query(
        "INSERT INTO roles (name, display_name, permissions, is_admin, created_at) \
         VALUES ($1, $1, $2, $3, now())",
    )
    .bind(name)
    .bind(sqlx::types::Json(permissions))
    .bind(is_admin)
    .execute(db)
    .await
    .unwrap();
}

/// admin roleのローカルユーザーをセッションCookie付きで1件用意する。
async fn seed_admin_session(db: &PgPool, redis: &redis::aio::ConnectionManager) -> String {
    let username = format!("admin{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(db, &username).await;
    let user_id = seed_user(db, actor_id, &format!("{username}@example.com")).await;
    set_user_role(db, user_id, "admin").await;
    seed_session(redis, user_id).await
}

fn cookie_header(session_id: &str) -> String {
    format!("nekonoverse_session={session_id}")
}

#[tokio::test]
async fn admin_domain_blocks_unauthenticated_returns_401() {
    let (app, _db) = test_app_with_db().await;
    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/domain_blocks")
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn admin_domain_blocks_plain_user_role_is_forbidden() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let username = format!("plain{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let user_id = seed_user(&db, actor_id, &format!("{username}@example.com")).await;
    let session_id = seed_session(&redis, user_id).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/domain_blocks")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn admin_domain_blocks_admin_roundtrip_create_list_delete() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let domain = format!("blocked-{}.example", Uuid::new_v4().simple());

    let create_req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/domain_blocks")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(
            json!({ "domain": domain, "severity": "suspend", "reason": "spam" }).to_string(),
        ))
        .unwrap();
    let resp = app.clone().oneshot(create_req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::CREATED);

    let list_req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/domain_blocks")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.clone().oneshot(list_req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);

    let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM domain_blocks WHERE domain = $1")
        .bind(&domain)
        .fetch_one(&db)
        .await
        .unwrap();
    assert_eq!(count, 1);

    let log_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM moderation_log WHERE action = 'domain_block' AND target_id = $1",
    )
    .bind(&domain)
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(log_count, 1);

    let delete_req = Request::builder()
        .method("DELETE")
        .uri(format!("/api/v1/admin/domain_blocks/{domain}"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(delete_req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);

    let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM domain_blocks WHERE domain = $1")
        .bind(&domain)
        .fetch_one(&db)
        .await
        .unwrap();
    assert_eq!(count, 0);

    let unblock_log_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM moderation_log WHERE action = 'domain_unblock' AND target_id = $1",
    )
    .bind(&domain)
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(unblock_log_count, 1);
}

#[tokio::test]
async fn admin_create_domain_block_duplicate_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let domain = format!("dup-{}.example", Uuid::new_v4().simple());

    for _ in 0..2 {
        let req = Request::builder()
            .method("POST")
            .uri("/api/v1/admin/domain_blocks")
            .header("cookie", cookie_header(&session_id))
            .header("content-type", "application/json")
            .body(Body::from(json!({ "domain": domain }).to_string()))
            .unwrap();
        let _ = app.clone().oneshot(req).await.unwrap();
    }

    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/domain_blocks")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(json!({ "domain": domain }).to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_create_domain_block_invalid_severity_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/domain_blocks")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(
            json!({ "domain": "example.com", "severity": "banhammer" }).to_string(),
        ))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_remove_nonexistent_domain_block_returns_404() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("DELETE")
        .uri(format!(
            "/api/v1/admin/domain_blocks/never-blocked-{}.example",
            Uuid::new_v4().simple()
        ))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn admin_custom_role_with_domains_permission_can_create() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let role_name = format!("moderator{}", Uuid::new_v4().simple());
    seed_role(&db, &role_name, false, json!({ "domains": true })).await;

    let username = format!("mod{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let user_id = seed_user(&db, actor_id, &format!("{username}@example.com")).await;
    set_user_role(&db, user_id, &role_name).await;
    let session_id = seed_session(&redis, user_id).await;

    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/domain_blocks")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(
            json!({ "domain": format!("modblock-{}.example", Uuid::new_v4().simple()) })
                .to_string(),
        ))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::CREATED);
}

#[tokio::test]
async fn admin_custom_role_without_domains_permission_is_forbidden() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let role_name = format!("helper{}", Uuid::new_v4().simple());
    seed_role(&db, &role_name, false, json!({ "reports": true })).await;

    let username = format!("helper{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let user_id = seed_user(&db, actor_id, &format!("{username}@example.com")).await;
    set_user_role(&db, user_id, &role_name).await;
    let session_id = seed_session(&redis, user_id).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/domain_blocks")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn admin_role_flagged_is_admin_bypasses_permissions_map() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let role_name = format!("superrole{}", Uuid::new_v4().simple());
    seed_role(&db, &role_name, true, json!({})).await;

    let username = format!("super{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let user_id = seed_user(&db, actor_id, &format!("{username}@example.com")).await;
    set_user_role(&db, user_id, &role_name).await;
    let session_id = seed_session(&redis, user_id).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/domain_blocks")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
}

#[tokio::test]
async fn admin_oauth_token_without_admin_scope_is_forbidden() {
    let (app, db) = test_app_with_db().await;
    let username = format!("oauth{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let user_id = seed_user(&db, actor_id, &format!("{username}@example.com")).await;
    set_user_role(&db, user_id, "admin").await;

    let app_id = seed_oauth_application(&db, "write").await;
    let token = seed_oauth_token(&db, app_id, user_id, "write", None, None).await;

    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/domain_blocks")
        .header("authorization", format!("Bearer {token}"))
        .header("content-type", "application/json")
        .body(Body::from(
            json!({ "domain": "oauth-blocked.example" }).to_string(),
        ))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn admin_oauth_token_with_admin_write_scope_can_create() {
    let (app, db) = test_app_with_db().await;
    let username = format!("oauth{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let user_id = seed_user(&db, actor_id, &format!("{username}@example.com")).await;
    set_user_role(&db, user_id, "admin").await;

    let app_id = seed_oauth_application(&db, "write admin:write").await;
    let token = seed_oauth_token(&db, app_id, user_id, "write admin:write", None, None).await;
    let domain = format!("oauth-ok-{}.example", Uuid::new_v4().simple());

    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/domain_blocks")
        .header("authorization", format!("Bearer {token}"))
        .header("content-type", "application/json")
        .body(Body::from(json!({ "domain": domain }).to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::CREATED);
}

#[tokio::test]
async fn admin_create_domain_block_invalidates_is_domain_blocked_cache() {
    use nekonoverse_backend_rs::domain_block::is_domain_blocked;
    use nekonoverse_backend_rs::{config::Config, state::AppState};

    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let domain = format!("cache-{}.example", Uuid::new_v4().simple());

    let state = AppState {
        db: db.clone(),
        redis: redis.clone(),
        config: Config::from_env(),
    };

    // ブロック作成前に一度呼び、"未ブロック"というキャッシュを意図的に温めておく。
    assert!(!is_domain_blocked(&state, &domain).await.unwrap());

    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/domain_blocks")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(json!({ "domain": domain }).to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::CREATED);

    // キャッシュが無効化され、TTL(300秒)を待たずに新しい状態が反映されるはず。
    assert!(is_domain_blocked(&state, &domain).await.unwrap());
}

/// 指定ロールのローカルユーザーをセッションCookie付きで1件用意する。
async fn seed_role_session(
    db: &PgPool,
    redis: &redis::aio::ConnectionManager,
    prefix: &str,
    role: &str,
) -> (Uuid, String) {
    let username = format!("{prefix}{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(db, &username).await;
    let user_id = seed_user(db, actor_id, &format!("{username}@example.com")).await;
    set_user_role(db, user_id, role).await;
    (user_id, seed_session(redis, user_id).await)
}

// --- 通報 (reports) ---

#[tokio::test]
async fn admin_list_reports_formats_acct_and_filters_by_status() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let reporter = seed_local_actor(&db, &format!("reporter{}", Uuid::new_v4().simple())).await;
    let domain = format!("remote-reports-{}.example", Uuid::new_v4().simple());
    let target = seed_remote_actor(&db, "reported", &domain).await;
    let report_id = seed_report(&db, reporter, target, None, Some("spam")).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/reports?status=open")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.clone().oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    let entry = json
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["id"] == report_id.to_string())
        .expect("seeded report present in open list");
    assert_eq!(entry["target"], format!("reported@{domain}"));
    assert_eq!(entry["comment"], "spam");
    assert_eq!(entry["status"], "open");

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/reports?status=resolved")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    let json = body_json(resp).await;
    assert!(json
        .as_array()
        .unwrap()
        .iter()
        .all(|r| r["id"] != report_id.to_string()));
}

#[tokio::test]
async fn admin_resolve_report_happy_path() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let reporter = seed_local_actor(&db, &format!("resolver{}", Uuid::new_v4().simple())).await;
    let target = seed_local_actor(&db, &format!("resolvee{}", Uuid::new_v4().simple())).await;
    let report_id = seed_report(&db, reporter, target, None, None).await;

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/reports/{report_id}/resolve"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);

    let status: String = sqlx::query_scalar("SELECT status FROM reports WHERE id = $1")
        .bind(report_id)
        .fetch_one(&db)
        .await
        .unwrap();
    assert_eq!(status, "resolved");

    let log_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM moderation_log WHERE action = 'resolve_report' AND target_id = $1",
    )
    .bind(report_id.to_string())
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(log_count, 1);
}

#[tokio::test]
async fn admin_reject_report_happy_path() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let reporter = seed_local_actor(&db, &format!("rejecter{}", Uuid::new_v4().simple())).await;
    let target = seed_local_actor(&db, &format!("rejectee{}", Uuid::new_v4().simple())).await;
    let report_id = seed_report(&db, reporter, target, None, None).await;

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/reports/{report_id}/reject"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);

    let status: String = sqlx::query_scalar("SELECT status FROM reports WHERE id = $1")
        .bind(report_id)
        .fetch_one(&db)
        .await
        .unwrap();
    assert_eq!(status, "rejected");
}

#[tokio::test]
async fn admin_resolve_already_handled_report_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let reporter = seed_local_actor(&db, &format!("dup{}", Uuid::new_v4().simple())).await;
    let target = seed_local_actor(&db, &format!("dup{}", Uuid::new_v4().simple())).await;
    let report_id = seed_report(&db, reporter, target, None, None).await;

    for _ in 0..2 {
        let req = Request::builder()
            .method("POST")
            .uri(format!("/api/v1/admin/reports/{report_id}/resolve"))
            .header("cookie", cookie_header(&session_id))
            .body(Body::empty())
            .unwrap();
        let _ = app.clone().oneshot(req).await.unwrap();
    }

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/reports/{report_id}/resolve"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_resolve_nonexistent_report_returns_404() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/reports/{}/resolve", Uuid::new_v4()))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn admin_reports_require_reports_permission_not_content() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let role_name = format!("contentonly{}", Uuid::new_v4().simple());
    seed_role(&db, &role_name, false, json!({ "content": true })).await;
    let (_uid, session_id) = seed_role_session(&db, &redis, "contentmod", &role_name).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/reports")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

// --- 投稿モデレーション (notes) ---

#[tokio::test]
async fn admin_delete_note_soft_deletes_and_delivers_to_follower() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let author = seed_local_actor(&db, &format!("delnote{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, author, "public", Utc::now()).await;
    let domain = format!("remote-delnote-{}.example", Uuid::new_v4().simple());
    let follower_id = seed_remote_actor(&db, "follower-delnote", &domain).await;
    seed_follow(&db, follower_id, author).await;

    let req = Request::builder()
        .method("DELETE")
        .uri(format!("/api/v1/admin/notes/{note_id}"))
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(
            json!({ "reason": "rule violation" }).to_string(),
        ))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);

    let deleted_at: Option<chrono::DateTime<Utc>> =
        sqlx::query_scalar("SELECT deleted_at FROM notes WHERE id = $1")
            .bind(note_id)
            .fetch_one(&db)
            .await
            .unwrap();
    assert!(deleted_at.is_some());

    let log_row: (String, Option<String>) = sqlx::query_as(
        "SELECT action, reason FROM moderation_log WHERE target_id = $1 \
         AND action = 'delete_note'",
    )
    .bind(note_id.to_string())
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(log_row.1.as_deref(), Some("rule violation"));

    let delete_row: (String, String) = sqlx::query_as(
        "SELECT target_inbox_url, payload->>'type' FROM delivery_queue \
         WHERE actor_id = $1 ORDER BY created_at DESC LIMIT 1",
    )
    .bind(author)
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(delete_row.0, format!("https://{domain}/inbox"));
    assert_eq!(delete_row.1, "Delete");
}

#[tokio::test]
async fn admin_delete_note_without_body_defaults_reason_none() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let author = seed_local_actor(&db, &format!("nobodynote{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, author, "public", Utc::now()).await;

    let req = Request::builder()
        .method("DELETE")
        .uri(format!("/api/v1/admin/notes/{note_id}"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);

    let reason: Option<String> = sqlx::query_scalar(
        "SELECT reason FROM moderation_log WHERE target_id = $1 AND action = 'delete_note'",
    )
    .bind(note_id.to_string())
    .fetch_one(&db)
    .await
    .unwrap();
    assert!(reason.is_none());
}

#[tokio::test]
async fn admin_delete_note_returns_404_for_missing_note() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("DELETE")
        .uri(format!("/api/v1/admin/notes/{}", Uuid::new_v4()))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn admin_delete_note_protects_staff_target_unless_admin() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let role_name = format!("contentmod{}", Uuid::new_v4().simple());
    seed_role(&db, &role_name, false, json!({ "content": true })).await;
    let (_uid, moderator_session) = seed_role_session(&db, &redis, "modacting", &role_name).await;

    // ターゲットは非adminのstaff (別のカスタムロール)。
    let target_role_name = format!("staffrole{}", Uuid::new_v4().simple());
    seed_role(&db, &target_role_name, false, json!({})).await;
    let target_username = format!("staffnote{}", Uuid::new_v4().simple());
    let target_actor = seed_local_actor(&db, &target_username).await;
    let target_user = seed_user(&db, target_actor, &format!("{target_username}@example.com")).await;
    set_user_role(&db, target_user, &target_role_name).await;
    let note_id = seed_note_with_visibility(&db, target_actor, "public", Utc::now()).await;

    let req = Request::builder()
        .method("DELETE")
        .uri(format!("/api/v1/admin/notes/{note_id}"))
        .header("cookie", cookie_header(&moderator_session))
        .body(Body::empty())
        .unwrap();
    let resp = app.clone().oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);

    let deleted_at: Option<chrono::DateTime<Utc>> =
        sqlx::query_scalar("SELECT deleted_at FROM notes WHERE id = $1")
            .bind(note_id)
            .fetch_one(&db)
            .await
            .unwrap();
    assert!(deleted_at.is_none());

    // adminはスタッフ保護をバイパスして削除できる。
    let admin_session = seed_admin_session(&db, &redis).await;
    let req = Request::builder()
        .method("DELETE")
        .uri(format!("/api/v1/admin/notes/{note_id}"))
        .header("cookie", cookie_header(&admin_session))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
}

#[tokio::test]
async fn admin_force_note_sensitive_happy_path() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let author = seed_local_actor(&db, &format!("sensitize{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, author, "public", Utc::now()).await;

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/notes/{note_id}/sensitive"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);

    let sensitive: bool = sqlx::query_scalar("SELECT sensitive FROM notes WHERE id = $1")
        .bind(note_id)
        .fetch_one(&db)
        .await
        .unwrap();
    assert!(sensitive);

    let log_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM moderation_log WHERE action = 'force_sensitive' AND target_id = $1",
    )
    .bind(note_id.to_string())
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(log_count, 1);
}

#[tokio::test]
async fn admin_notes_actions_require_content_permission_not_reports() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let role_name = format!("reportsonly{}", Uuid::new_v4().simple());
    seed_role(&db, &role_name, false, json!({ "reports": true })).await;
    let (_uid, session_id) = seed_role_session(&db, &redis, "reportsmod", &role_name).await;
    let author = seed_local_actor(&db, &format!("guardednote{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, author, "public", Utc::now()).await;

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/notes/{note_id}/sensitive"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

// --- モデレーションログ (log) ---

#[tokio::test]
async fn admin_log_returns_recent_entries_for_admin() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let domain = format!("logentry-{}.example", Uuid::new_v4().simple());

    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/domain_blocks")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(json!({ "domain": domain }).to_string()))
        .unwrap();
    let resp = app.clone().oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::CREATED);

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/log")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    let entries = json.as_array().unwrap();
    assert!(entries
        .iter()
        .any(|e| e["action"] == "domain_block" && e["target_id"] == domain));
}

#[tokio::test]
async fn admin_log_accessible_with_any_single_moderator_permission() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let role_name = format!("domainsonly{}", Uuid::new_v4().simple());
    seed_role(&db, &role_name, false, json!({ "domains": true })).await;
    let (_uid, session_id) = seed_role_session(&db, &redis, "logviewer", &role_name).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/log")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
}

#[tokio::test]
async fn admin_log_forbidden_for_role_without_any_permission() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let role_name = format!("nopermsrole{}", Uuid::new_v4().simple());
    seed_role(&db, &role_name, false, json!({})).await;
    let (_uid, session_id) = seed_role_session(&db, &redis, "noperms", &role_name).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/log")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn admin_log_limit_out_of_range_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/log?limit=0")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.clone().oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/log?limit=101")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

// --- ロール (roles) ---

#[tokio::test]
async fn admin_list_roles_orders_builtins_by_priority_desc() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/roles")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    let names: Vec<String> = json
        .as_array()
        .unwrap()
        .iter()
        .map(|r| r["name"].as_str().unwrap().to_string())
        .collect();
    // 組み込みroleのpriority: admin=100, moderator=50, user=0。
    let admin_idx = names.iter().position(|n| n == "admin").unwrap();
    let moderator_idx = names.iter().position(|n| n == "moderator").unwrap();
    let user_idx = names.iter().position(|n| n == "user").unwrap();
    assert!(admin_idx < moderator_idx);
    assert!(moderator_idx < user_idx);
}

#[tokio::test]
async fn admin_get_role_returns_404_for_missing_role() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("GET")
        .uri(format!(
            "/api/v1/admin/roles/nosuchrole{}",
            Uuid::new_v4().simple()
        ))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn admin_get_role_returns_builtin_admin_role() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/roles/admin")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    assert_eq!(json["name"], "admin");
    assert_eq!(json["is_admin"], true);
    assert_eq!(json["is_system"], true);
    assert_eq!(json["priority"], 100);
}

#[tokio::test]
async fn admin_create_role_with_defaults() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let name = format!("newrole{}", Uuid::new_v4().simple());

    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/roles")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(
            json!({ "name": name, "display_name": "New Role" }).to_string(),
        ))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::CREATED);
    let json = body_json(resp).await;
    assert_eq!(json["name"], name);
    assert_eq!(json["display_name"], "New Role");
    assert_eq!(json["permissions"], json!({}));
    assert_eq!(json["quota_bytes"], 1_073_741_824i64);
    assert_eq!(json["priority"], 0);
    assert_eq!(json["is_system"], false);
}

#[tokio::test]
async fn admin_create_role_with_copy_from_inherits_source_fields() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let source_name = format!("source{}", Uuid::new_v4().simple());
    seed_role(&db, &source_name, false, json!({ "content": true })).await;
    sqlx::query("UPDATE roles SET quota_bytes = 999, priority = 7 WHERE name = $1")
        .bind(&source_name)
        .execute(&db)
        .await
        .unwrap();

    let new_name = format!("copy{}", Uuid::new_v4().simple());
    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/roles")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(
            json!({ "name": new_name, "display_name": "Copy", "copy_from": source_name })
                .to_string(),
        ))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::CREATED);
    let json = body_json(resp).await;
    assert_eq!(json["permissions"], json!({ "content": true }));
    assert_eq!(json["quota_bytes"], 999);
    assert_eq!(json["priority"], 7);
}

#[tokio::test]
async fn admin_create_role_duplicate_name_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let name = format!("dup{}", Uuid::new_v4().simple());
    seed_role(&db, &name, false, json!({})).await;

    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/roles")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(
            json!({ "name": name, "display_name": "Dup" }).to_string(),
        ))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_create_role_invalid_name_pattern_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/roles")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(
            json!({ "name": "Invalid-Name", "display_name": "x" }).to_string(),
        ))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_roles_endpoints_require_literal_admin_role_not_is_admin_flag() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    // permissions JSONBのis_adminフラグを立てたカスタムroleでも、
    // get_admin_user相当(role文字列が"admin"かどうか)は満たさない。
    let role_name = format!("superadmin{}", Uuid::new_v4().simple());
    seed_role(&db, &role_name, true, json!({})).await;
    let (_uid, session_id) = seed_role_session(&db, &redis, "notreallyadmin", &role_name).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/roles")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn admin_update_role_partially_updates_only_given_fields() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let name = format!("updatable{}", Uuid::new_v4().simple());
    seed_role(&db, &name, false, json!({ "content": true })).await;

    let req = Request::builder()
        .method("PATCH")
        .uri(format!("/api/v1/admin/roles/{name}"))
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(json!({ "priority": 42 }).to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    assert_eq!(json["priority"], 42);
    // display_name/permissionsは変更されず維持される。
    assert_eq!(json["display_name"], name);
    assert_eq!(json["permissions"], json!({ "content": true }));
}

#[tokio::test]
async fn admin_update_nonexistent_role_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("PATCH")
        .uri(format!(
            "/api/v1/admin/roles/nosuchrole{}",
            Uuid::new_v4().simple()
        ))
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(json!({ "priority": 1 }).to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_delete_role_happy_path() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let name = format!("deletable{}", Uuid::new_v4().simple());
    seed_role(&db, &name, false, json!({})).await;

    let req = Request::builder()
        .method("DELETE")
        .uri(format!("/api/v1/admin/roles/{name}"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::NO_CONTENT);

    let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM roles WHERE name = $1")
        .bind(&name)
        .fetch_one(&db)
        .await
        .unwrap();
    assert_eq!(count, 0);
}

#[tokio::test]
async fn admin_delete_role_nonexistent_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("DELETE")
        .uri(format!(
            "/api/v1/admin/roles/nosuchrole{}",
            Uuid::new_v4().simple()
        ))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_delete_builtin_role_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("DELETE")
        .uri("/api/v1/admin/roles/moderator")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);

    let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM roles WHERE name = 'moderator'")
        .fetch_one(&db)
        .await
        .unwrap();
    assert_eq!(count, 1);
}

#[tokio::test]
async fn admin_delete_role_with_assigned_users_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let name = format!("occupied{}", Uuid::new_v4().simple());
    seed_role(&db, &name, false, json!({})).await;
    let (_uid, _session) = seed_role_session(&db, &redis, "occupant", &name).await;

    let req = Request::builder()
        .method("DELETE")
        .uri(format!("/api/v1/admin/roles/{name}"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

// --- レガシーのモデレーター権限ショートカット (permissions) ---

#[tokio::test]
async fn admin_get_permissions_returns_seven_known_keys_as_booleans() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/permissions")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    let obj = json.as_object().unwrap();
    for key in [
        "users",
        "reports",
        "content",
        "domains",
        "federation",
        "emoji",
        "registrations",
    ] {
        assert!(obj.get(key).unwrap().is_boolean(), "missing key {key}");
    }
    // role_service側の8キーには含まれる"announcements"はレガシー版に含まない。
    assert!(!obj.contains_key("announcements"));
}

#[tokio::test]
async fn admin_get_permissions_accessible_to_non_admin_staff() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let role_name = format!("juststaff{}", Uuid::new_v4().simple());
    seed_role(&db, &role_name, false, json!({})).await;
    let (_uid, session_id) = seed_role_session(&db, &redis, "juststaff", &role_name).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/permissions")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
}

#[tokio::test]
async fn admin_update_permissions_requires_admin_not_just_staff() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let role_name = format!("modonly{}", Uuid::new_v4().simple());
    seed_role(&db, &role_name, false, json!({ "users": true })).await;
    let (_uid, session_id) = seed_role_session(&db, &redis, "modonly", &role_name).await;

    let req = Request::builder()
        .method("PATCH")
        .uri("/api/v1/admin/permissions")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(json!({ "users": false }).to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

/// "moderator" roleの`permissions`は他の権限系テストとも共有される単一行
/// なので、レース回避のためPATCHして検証するテストはこの1本にまとめる。
#[tokio::test]
async fn admin_update_permissions_sets_known_keys_and_ignores_unknown() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let marker = format!("probe-{}", Uuid::new_v4().simple());

    let req = Request::builder()
        .method("PATCH")
        .uri("/api/v1/admin/permissions")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(
            json!({ "domains": false, "emoji": true, marker.clone(): true }).to_string(),
        ))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    assert_eq!(json["domains"], false);
    assert_eq!(json["emoji"], true);
    assert!(json.as_object().unwrap().get(&marker).is_none());

    let stored: Value =
        sqlx::query_scalar("SELECT permissions FROM roles WHERE name = 'moderator'")
            .fetch_one(&db)
            .await
            .unwrap();
    assert_eq!(stored["domains"], false);
    assert!(stored.get(&marker).is_none());
}

// --- ユーザー管理 (users) ---

#[tokio::test]
async fn admin_list_users_returns_seeded_user() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let username = format!("listee{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let user_id = seed_user(&db, actor_id, &format!("{username}@example.com")).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/users")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    let entry = json
        .as_array()
        .unwrap()
        .iter()
        .find(|u| u["id"] == user_id.to_string())
        .expect("seeded user present in list");
    assert_eq!(entry["username"], username);
    assert_eq!(entry["role"], "user");
    assert_eq!(entry["is_active"], true);
    assert_eq!(entry["is_system"], false);
    assert_eq!(entry["suspended"], false);
    assert_eq!(entry["silenced"], false);
    assert_eq!(entry["storage_usage_bytes"], 0);
}

#[tokio::test]
async fn admin_list_users_limit_over_100_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/users?limit=101")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_users_endpoints_require_users_permission_not_content() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let role_name = format!("contentonly{}", Uuid::new_v4().simple());
    seed_role(&db, &role_name, false, json!({ "content": true })).await;
    let (_uid, session_id) = seed_role_session(&db, &redis, "contentmod", &role_name).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/users")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

async fn seed_target_user(db: &PgPool, prefix: &str) -> (Uuid, Uuid, String) {
    let username = format!("{prefix}{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(db, &username).await;
    let user_id = seed_user(db, actor_id, &format!("{username}@example.com")).await;
    (user_id, actor_id, username)
}

#[tokio::test]
async fn admin_change_user_role_happy_path() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let (target_user, target_actor, _username) = seed_target_user(&db, "rolechange").await;

    let req = Request::builder()
        .method("PATCH")
        .uri(format!("/api/v1/admin/users/{target_user}/role"))
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(json!({ "role": "moderator" }).to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    assert_eq!(json["ok"], true);
    assert_eq!(json["role"], "moderator");

    let role: String = sqlx::query_scalar("SELECT role FROM users WHERE id = $1")
        .bind(target_user)
        .fetch_one(&db)
        .await
        .unwrap();
    assert_eq!(role, "moderator");

    let log_row: (String, Option<String>) = sqlx::query_as(
        "SELECT action, reason FROM moderation_log WHERE target_id = $1 AND action = 'role_change'",
    )
    .bind(target_actor.to_string())
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(log_row.1.as_deref(), Some("user -> moderator"));
}

#[tokio::test]
async fn admin_change_user_role_nonexistent_role_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let (target_user, _target_actor, _username) = seed_target_user(&db, "badrole").await;

    let req = Request::builder()
        .method("PATCH")
        .uri(format!("/api/v1/admin/users/{target_user}/role"))
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(
            json!({ "role": format!("nosuchrole{}", Uuid::new_v4().simple()) }).to_string(),
        ))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_change_user_role_cannot_change_own_role_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let username = format!("selfrole{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let user_id = seed_user(&db, actor_id, &format!("{username}@example.com")).await;
    set_user_role(&db, user_id, "admin").await;
    let session_id = seed_session(&redis, user_id).await;

    let req = Request::builder()
        .method("PATCH")
        .uri(format!("/api/v1/admin/users/{user_id}/role"))
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(json!({ "role": "moderator" }).to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_change_user_role_requires_admin_not_just_users_permission() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let role_name = format!("usersonly{}", Uuid::new_v4().simple());
    seed_role(&db, &role_name, false, json!({ "users": true })).await;
    let (_uid, session_id) = seed_role_session(&db, &redis, "usersmod", &role_name).await;
    let (target_user, _target_actor, _username) = seed_target_user(&db, "roleforbidden").await;

    let req = Request::builder()
        .method("PATCH")
        .uri(format!("/api/v1/admin/users/{target_user}/role"))
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(json!({ "role": "moderator" }).to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn admin_change_user_role_returns_404_for_missing_user() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("PATCH")
        .uri(format!("/api/v1/admin/users/{}/role", Uuid::new_v4()))
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(json!({ "role": "moderator" }).to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn admin_suspend_user_soft_deletes_notes_invalidates_sessions_and_delivers_delete() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let (target_user, target_actor, target_username) = seed_target_user(&db, "suspendee").await;
    let note_id = seed_note_with_visibility(&db, target_actor, "public", Utc::now()).await;
    let domain = format!("remote-suspend-{}.example", Uuid::new_v4().simple());
    let follower_id = seed_remote_actor(&db, "follower-suspend", &domain).await;
    seed_follow(&db, follower_id, target_actor).await;
    let target_session = seed_session(&redis, target_user).await;

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/users/{target_user}/suspend"))
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(json!({ "reason": "spam" }).to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);

    let suspended_at: Option<chrono::DateTime<Utc>> =
        sqlx::query_scalar("SELECT suspended_at FROM actors WHERE id = $1")
            .bind(target_actor)
            .fetch_one(&db)
            .await
            .unwrap();
    assert!(suspended_at.is_some());

    let deleted_at: Option<chrono::DateTime<Utc>> =
        sqlx::query_scalar("SELECT deleted_at FROM notes WHERE id = $1")
            .bind(note_id)
            .fetch_one(&db)
            .await
            .unwrap();
    assert!(deleted_at.is_some());

    let log_row: (String, Option<String>) = sqlx::query_as(
        "SELECT action, reason FROM moderation_log WHERE target_id = $1 AND action = 'suspend'",
    )
    .bind(target_actor.to_string())
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(log_row.1.as_deref(), Some("spam"));

    let mut conn = redis.clone();
    let exists: bool = conn
        .exists(format!("session:{target_session}"))
        .await
        .unwrap();
    assert!(!exists, "suspended user's session should be invalidated");

    let delete_row: (String, String, String) = sqlx::query_as(
        "SELECT target_inbox_url, payload->>'type', payload->'object'->>'id' FROM delivery_queue \
         WHERE actor_id = $1 ORDER BY created_at DESC LIMIT 1",
    )
    .bind(target_actor)
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(delete_row.0, format!("https://{domain}/inbox"));
    assert_eq!(delete_row.1, "Delete");
    assert_eq!(
        delete_row.2,
        format!("https://localhost/users/{target_username}")
    );
}

#[tokio::test]
async fn admin_suspend_user_already_suspended_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let (target_user, _target_actor, _username) = seed_target_user(&db, "resuspend").await;

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/users/{target_user}/suspend"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.clone().oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/users/{target_user}/suspend"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_suspend_user_cannot_suspend_self_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let username = format!("selfsuspend{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let user_id = seed_user(&db, actor_id, &format!("{username}@example.com")).await;
    set_user_role(&db, user_id, "admin").await;
    let session_id = seed_session(&redis, user_id).await;

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/users/{user_id}/suspend"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_suspend_user_rejects_system_account() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let (target_user, _target_actor, _username) = seed_target_user(&db, "systemacct").await;
    set_user_is_system(&db, target_user).await;

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/users/{target_user}/suspend"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_suspend_user_protects_staff_target_unless_admin() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let role_name = format!("usersmod{}", Uuid::new_v4().simple());
    seed_role(&db, &role_name, false, json!({ "users": true })).await;
    let (_uid, moderator_session) = seed_role_session(&db, &redis, "actingmod", &role_name).await;

    let target_role_name = format!("staffrole{}", Uuid::new_v4().simple());
    seed_role(&db, &target_role_name, false, json!({})).await;
    let (target_user, target_actor, _username) = seed_target_user(&db, "staffsuspend").await;
    set_user_role(&db, target_user, &target_role_name).await;

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/users/{target_user}/suspend"))
        .header("cookie", cookie_header(&moderator_session))
        .body(Body::empty())
        .unwrap();
    let resp = app.clone().oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);

    let suspended_at: Option<chrono::DateTime<Utc>> =
        sqlx::query_scalar("SELECT suspended_at FROM actors WHERE id = $1")
            .bind(target_actor)
            .fetch_one(&db)
            .await
            .unwrap();
    assert!(suspended_at.is_none());

    let admin_session = seed_admin_session(&db, &redis).await;
    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/users/{target_user}/suspend"))
        .header("cookie", cookie_header(&admin_session))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
}

#[tokio::test]
async fn admin_unsuspend_user_happy_path() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let (target_user, target_actor, _username) = seed_target_user(&db, "unsuspend").await;
    sqlx::query("UPDATE actors SET suspended_at = now() WHERE id = $1")
        .bind(target_actor)
        .execute(&db)
        .await
        .unwrap();

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/users/{target_user}/unsuspend"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);

    let suspended_at: Option<chrono::DateTime<Utc>> =
        sqlx::query_scalar("SELECT suspended_at FROM actors WHERE id = $1")
            .bind(target_actor)
            .fetch_one(&db)
            .await
            .unwrap();
    assert!(suspended_at.is_none());

    let log_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM moderation_log WHERE action = 'unsuspend' AND target_id = $1",
    )
    .bind(target_actor.to_string())
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(log_count, 1);
}

#[tokio::test]
async fn admin_unsuspend_user_not_suspended_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let (target_user, _target_actor, _username) = seed_target_user(&db, "notsuspended").await;

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/users/{target_user}/unsuspend"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_silence_user_happy_path() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let (target_user, target_actor, _username) = seed_target_user(&db, "silencee").await;

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/users/{target_user}/silence"))
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(
            json!({ "reason": "repeated rule violations" }).to_string(),
        ))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);

    let silenced_at: Option<chrono::DateTime<Utc>> =
        sqlx::query_scalar("SELECT silenced_at FROM actors WHERE id = $1")
            .bind(target_actor)
            .fetch_one(&db)
            .await
            .unwrap();
    assert!(silenced_at.is_some());

    let log_row: (String, Option<String>) = sqlx::query_as(
        "SELECT action, reason FROM moderation_log WHERE target_id = $1 AND action = 'silence'",
    )
    .bind(target_actor.to_string())
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(log_row.1.as_deref(), Some("repeated rule violations"));
}

#[tokio::test]
async fn admin_silence_user_already_silenced_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let (target_user, target_actor, _username) = seed_target_user(&db, "resilence").await;
    sqlx::query("UPDATE actors SET silenced_at = now() WHERE id = $1")
        .bind(target_actor)
        .execute(&db)
        .await
        .unwrap();

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/users/{target_user}/silence"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_silence_user_cannot_silence_self_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let username = format!("selfsilence{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let user_id = seed_user(&db, actor_id, &format!("{username}@example.com")).await;
    set_user_role(&db, user_id, "admin").await;
    let session_id = seed_session(&redis, user_id).await;

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/users/{user_id}/silence"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_unsilence_user_happy_path() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let (target_user, target_actor, _username) = seed_target_user(&db, "unsilence").await;
    sqlx::query("UPDATE actors SET silenced_at = now() WHERE id = $1")
        .bind(target_actor)
        .execute(&db)
        .await
        .unwrap();

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/users/{target_user}/unsilence"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);

    let silenced_at: Option<chrono::DateTime<Utc>> =
        sqlx::query_scalar("SELECT silenced_at FROM actors WHERE id = $1")
            .bind(target_actor)
            .fetch_one(&db)
            .await
            .unwrap();
    assert!(silenced_at.is_none());
}

#[tokio::test]
async fn admin_unsilence_user_not_silenced_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let (target_user, _target_actor, _username) = seed_target_user(&db, "notsilenced").await;

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/users/{target_user}/unsilence"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_suspend_user_returns_404_for_missing_user() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/users/{}/suspend", Uuid::new_v4()))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);
}

// --- キュー管理 (queue_service) ---

#[tokio::test]
async fn admin_queue_stats_unauthenticated_returns_401() {
    let (app, _db) = test_app_with_db().await;
    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/queue/stats")
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn admin_queue_stats_requires_literal_admin_role_not_permission() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    // "queue"権限相当のものはPython版に存在せず、get_admin_user
    // (role文字列が"admin"かどうか)のみが判定基準。permissions JSONBで
    // is_adminを立てたカスタムroleでも通らないことを確認する。
    let role_name = format!("queueadmin{}", Uuid::new_v4().simple());
    seed_role(&db, &role_name, true, json!({})).await;
    let (_uid, session_id) = seed_role_session(&db, &redis, "queuenotadmin", &role_name).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/queue/stats")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn admin_queue_stats_response_shape_is_internally_consistent() {
    // `delivery_queue` はテーブル全体を集計する(テストごとに隔離されていない)
    // ため、他のテストと並列実行しているとpending/processing/delivered/dead
    // の絶対値・差分は両方とも揺れうる。ここでは単一レスポンス内で常に
    // 成り立つはずの不変条件(total = 内訳の合計)のみを検証する。
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/queue/stats")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;

    let field = |key: &str| json[key].as_i64().unwrap();
    assert_eq!(
        field("total"),
        field("pending") + field("processing") + field("delivered") + field("dead")
    );
    assert!(field("recent_delivered") <= field("delivered"));
    assert!(field("recent_dead") <= field("dead"));
}

#[tokio::test]
async fn admin_queue_stats_recent_counts_use_current_hour_start_as_boundary() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let actor_id = seed_local_actor(&db, &format!("queuestats{}", Uuid::new_v4().simple())).await;
    let inbox = format!("https://stats-{}.example/inbox", Uuid::new_v4().simple());

    // `last_attempted_at`を明示的にセットするテストは他に存在しないため、
    // `recent_dead`はこのテスト自身が挿入する行以外では並列実行中の他テストと
    // 衝突しにくい(それらは`last_attempted_at`をNULLのまま`pending`で
    // 投入するのみで、seed直後は集計対象にならない)。それでもUPDATEの前後で
    // 差分を取ることで、たとえ他の要因で絶対値が動いても検証できるようにする。
    let dead_recent = seed_delivery_job(&db, actor_id, &inbox, "dead").await;
    let dead_stale = seed_delivery_job(&db, actor_id, &inbox, "dead").await;

    let before = {
        let req = Request::builder()
            .method("GET")
            .uri("/api/v1/admin/queue/stats")
            .header("cookie", cookie_header(&session_id))
            .body(Body::empty())
            .unwrap();
        body_json(app.clone().oneshot(req).await.unwrap()).await
    };

    // 「直近」判定は現在時刻の1時間前ではなく「今の時(hour)の開始時刻」を
    // 境界に使う(Python版 `queue_service.get_queue_stats` の実際の挙動)。
    // 境界内(今の時の開始時刻ちょうど)は集計対象、境界より前(前の時の
    // 最後の1秒)は対象外になることを確認する。
    sqlx::query(
        "UPDATE delivery_queue SET last_attempted_at = date_trunc('hour', now()) WHERE id = $1",
    )
    .bind(dead_recent)
    .execute(&db)
    .await
    .unwrap();
    sqlx::query(
        "UPDATE delivery_queue SET last_attempted_at = date_trunc('hour', now()) - interval '1 second' WHERE id = $1",
    )
    .bind(dead_stale)
    .execute(&db)
    .await
    .unwrap();

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/queue/stats")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let after = body_json(resp).await;

    assert_eq!(
        after["recent_dead"].as_i64().unwrap() - before["recent_dead"].as_i64().unwrap(),
        1
    );
}

#[tokio::test]
async fn admin_queue_jobs_lists_ordered_desc_with_total() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let actor_id = seed_local_actor(&db, &format!("queuejobs{}", Uuid::new_v4().simple())).await;
    // `domain`でこのテスト専有のホストに絞り込み、`delivery_queue`が
    // テスト間で共有される(ワークスペース全体を並列実行すると他ファイルの
    // テストも行を挿入する)ことの影響を受けないようにする。デフォルトの
    // limit=50に頼ると、大量に挿入された他テストの行に押し出されて自分の
    // 行が結果に含まれない場合がある。
    let domain = format!("jobs-{}.example", Uuid::new_v4().simple());
    let inbox = format!("https://{domain}/inbox");

    let older = seed_delivery_job(&db, actor_id, &inbox, "pending").await;
    sqlx::query("UPDATE delivery_queue SET created_at = now() - interval '1 hour' WHERE id = $1")
        .bind(older)
        .execute(&db)
        .await
        .unwrap();
    let newer = seed_delivery_job(&db, actor_id, &inbox, "pending").await;

    let req = Request::builder()
        .method("GET")
        .uri(format!("/api/v1/admin/queue/jobs?domain={domain}"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    let jobs = json["jobs"].as_array().unwrap();
    let ids: Vec<String> = jobs
        .iter()
        .map(|j| j["id"].as_str().unwrap().to_string())
        .collect();
    let newer_pos = ids.iter().position(|id| id == &newer.to_string()).unwrap();
    let older_pos = ids.iter().position(|id| id == &older.to_string()).unwrap();
    assert!(newer_pos < older_pos);
    assert_eq!(json["total"], 2);
}

#[tokio::test]
async fn admin_queue_jobs_filters_by_status_and_domain() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let actor_id = seed_local_actor(&db, &format!("queuefilter{}", Uuid::new_v4().simple())).await;
    let domain = format!("filter-{}.example", Uuid::new_v4().simple());
    let matching_inbox = format!("https://{domain}/inbox");
    let other_inbox = format!("https://other-{}.example/inbox", Uuid::new_v4().simple());

    let matching = seed_delivery_job(&db, actor_id, &matching_inbox, "dead").await;
    seed_delivery_job(&db, actor_id, &matching_inbox, "pending").await;
    seed_delivery_job(&db, actor_id, &other_inbox, "dead").await;

    let req = Request::builder()
        .method("GET")
        .uri(format!(
            "/api/v1/admin/queue/jobs?status=dead&domain={domain}"
        ))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    let jobs = json["jobs"].as_array().unwrap();
    assert_eq!(jobs.len(), 1);
    assert_eq!(jobs[0]["id"], matching.to_string());
    assert_eq!(json["total"], 1);
}

#[tokio::test]
async fn admin_queue_jobs_limit_out_of_range_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/queue/jobs?limit=201")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_queue_jobs_negative_offset_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/queue/jobs?offset=-1")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_retry_queue_job_resets_dead_job_to_pending() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let actor_id = seed_local_actor(&db, &format!("queueretry{}", Uuid::new_v4().simple())).await;
    let inbox = format!("https://retry-{}.example/inbox", Uuid::new_v4().simple());
    let job_id = seed_delivery_job(&db, actor_id, &inbox, "dead").await;
    sqlx::query(
        "UPDATE delivery_queue SET attempts = 10, error_message = 'boom', \
         next_retry_at = now() WHERE id = $1",
    )
    .bind(job_id)
    .execute(&db)
    .await
    .unwrap();

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/queue/retry/{job_id}"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);

    let row: (String, i32, Option<String>, Option<chrono::DateTime<Utc>>) = sqlx::query_as(
        "SELECT status, attempts, error_message, next_retry_at FROM delivery_queue WHERE id = $1",
    )
    .bind(job_id)
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(row.0, "pending");
    assert_eq!(row.1, 0);
    assert!(row.2.is_none());
    assert!(row.3.is_none());
}

#[tokio::test]
async fn admin_retry_queue_job_returns_404_when_not_dead() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let actor_id = seed_local_actor(&db, &format!("queuenotdead{}", Uuid::new_v4().simple())).await;
    let inbox = format!("https://notdead-{}.example/inbox", Uuid::new_v4().simple());
    let job_id = seed_delivery_job(&db, actor_id, &inbox, "pending").await;

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/queue/retry/{job_id}"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn admin_retry_queue_job_returns_404_for_missing_job() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/queue/retry/{}", Uuid::new_v4()))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn admin_retry_all_dead_jobs_filters_by_domain() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let actor_id =
        seed_local_actor(&db, &format!("queueretryall{}", Uuid::new_v4().simple())).await;
    let domain = format!("retryall-{}.example", Uuid::new_v4().simple());
    let matching_inbox = format!("https://{domain}/inbox");
    let other_inbox = format!("https://other-{}.example/inbox", Uuid::new_v4().simple());

    let matching = seed_delivery_job(&db, actor_id, &matching_inbox, "dead").await;
    let other = seed_delivery_job(&db, actor_id, &other_inbox, "dead").await;

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/queue/retry-all?domain={domain}"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    assert_eq!(json["retried"], 1);

    let matching_status: String =
        sqlx::query_scalar("SELECT status FROM delivery_queue WHERE id = $1")
            .bind(matching)
            .fetch_one(&db)
            .await
            .unwrap();
    assert_eq!(matching_status, "pending");
    let other_status: String =
        sqlx::query_scalar("SELECT status FROM delivery_queue WHERE id = $1")
            .bind(other)
            .fetch_one(&db)
            .await
            .unwrap();
    assert_eq!(other_status, "dead");
}

#[tokio::test]
async fn admin_purge_delivered_jobs_removes_only_old_delivered() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let actor_id = seed_local_actor(&db, &format!("queuepurge{}", Uuid::new_v4().simple())).await;
    let inbox = format!("https://purge-{}.example/inbox", Uuid::new_v4().simple());

    let old_delivered = seed_delivery_job(&db, actor_id, &inbox, "delivered").await;
    sqlx::query("UPDATE delivery_queue SET created_at = now() - interval '48 hours' WHERE id = $1")
        .bind(old_delivered)
        .execute(&db)
        .await
        .unwrap();
    let recent_delivered = seed_delivery_job(&db, actor_id, &inbox, "delivered").await;
    let old_dead = seed_delivery_job(&db, actor_id, &inbox, "dead").await;
    sqlx::query("UPDATE delivery_queue SET created_at = now() - interval '48 hours' WHERE id = $1")
        .bind(old_dead)
        .execute(&db)
        .await
        .unwrap();

    let req = Request::builder()
        .method("DELETE")
        .uri("/api/v1/admin/queue/purge?older_than_hours=24")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    assert_eq!(json["purged"], 1);

    let remaining: Vec<Uuid> =
        sqlx::query_scalar("SELECT id FROM delivery_queue WHERE id = ANY($1)")
            .bind(&[old_delivered, recent_delivered, old_dead][..])
            .fetch_all(&db)
            .await
            .unwrap();
    assert!(!remaining.contains(&old_delivered));
    assert!(remaining.contains(&recent_delivered));
    assert!(remaining.contains(&old_dead));
}

#[tokio::test]
async fn admin_purge_delivered_jobs_older_than_hours_below_minimum_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("DELETE")
        .uri("/api/v1/admin/queue/purge?older_than_hours=0")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

// --- 登録承認 (registrations) ---

async fn seed_pending_user(
    db: &PgPool,
    prefix: &str,
    reason: Option<&str>,
) -> (Uuid, Uuid, String) {
    let (user_id, actor_id, username) = seed_target_user(db, prefix).await;
    sqlx::query(
        "UPDATE users SET approval_status = 'pending', registration_reason = $2 WHERE id = $1",
    )
    .bind(user_id)
    .bind(reason)
    .execute(db)
    .await
    .unwrap();
    (user_id, actor_id, username)
}

#[tokio::test]
async fn admin_list_pending_registrations_returns_pending_only() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let (pending_id, _actor_id, pending_username) =
        seed_pending_user(&db, "pendingreg", Some("please let me in")).await;
    let (approved_id, _approved_actor, _approved_username) =
        seed_target_user(&db, "approvedreg").await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/registrations")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    let entries = json.as_array().unwrap();
    assert!(entries.iter().all(|r| r["id"] != approved_id.to_string()));
    let entry = entries
        .iter()
        .find(|r| r["id"] == pending_id.to_string())
        .expect("seeded pending registration present in list");
    assert_eq!(entry["username"], pending_username);
    assert_eq!(entry["reason"], "please let me in");
}

#[tokio::test]
async fn admin_approve_registration_happy_path() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let (target_user, _target_actor, _username) = seed_pending_user(&db, "approvee", None).await;

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/registrations/{target_user}/approve"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);

    let approval_status: String =
        sqlx::query_scalar("SELECT approval_status FROM users WHERE id = $1")
            .bind(target_user)
            .fetch_one(&db)
            .await
            .unwrap();
    assert_eq!(approval_status, "approved");

    let log_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM moderation_log \
         WHERE action = 'approve_registration' AND target_id = $1",
    )
    .bind(target_user.to_string())
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(log_count, 1);
}

#[tokio::test]
async fn admin_approve_registration_already_approved_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let (target_user, _target_actor, _username) = seed_target_user(&db, "alreadyapproved").await;

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/registrations/{target_user}/approve"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_approve_registration_returns_404_for_missing_user() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("POST")
        .uri(format!(
            "/api/v1/admin/registrations/{}/approve",
            Uuid::new_v4()
        ))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn admin_reject_registration_deletes_user_and_actor() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let (target_user, target_actor, _username) = seed_pending_user(&db, "rejectee", None).await;

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/registrations/{target_user}/reject"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);

    let user_exists: bool = sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM users WHERE id = $1)")
        .bind(target_user)
        .fetch_one(&db)
        .await
        .unwrap();
    assert!(!user_exists);
    let actor_exists: bool =
        sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM actors WHERE id = $1)")
            .bind(target_actor)
            .fetch_one(&db)
            .await
            .unwrap();
    assert!(!actor_exists);

    let log_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM moderation_log \
         WHERE action = 'reject_registration' AND target_id = $1",
    )
    .bind(target_user.to_string())
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(log_count, 1);
}

#[tokio::test]
async fn admin_reject_registration_already_handled_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let (target_user, _target_actor, _username) = seed_target_user(&db, "handledreject").await;

    let req = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/admin/registrations/{target_user}/reject"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_registrations_require_registrations_permission_not_users() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let role_name = format!("usersonlyreg{}", Uuid::new_v4().simple());
    seed_role(&db, &role_name, false, json!({ "users": true })).await;
    let (_uid, session_id) = seed_role_session(&db, &redis, "usersonlyregmod", &role_name).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/registrations")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn admin_registrations_unauthenticated_returns_401() {
    let (app, _db) = test_app_with_db().await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/registrations")
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
}

// --- 連合サーバー一覧/詳細 (federation) ---

/// `domain_blocks`にseverity/reasonを指定してテスト用のドメインブロックを
/// 1件投入する(`common::seed_domain_block`はseverity列のDB defaultである
/// `'suspend'`固定・reasonなしのため、silence系のテストには使えない)。
async fn seed_domain_block_full(db: &PgPool, domain: &str, severity: &str, reason: Option<&str>) {
    sqlx::query(
        "INSERT INTO domain_blocks (id, domain, severity, reason, created_at) \
         VALUES ($1, $2, $3, $4, now())",
    )
    .bind(Uuid::new_v4())
    .bind(domain)
    .bind(severity)
    .bind(reason)
    .execute(db)
    .await
    .unwrap();
}

/// `local = false`のノートを1件投入する(`common::seed_note_with_visibility`は
/// `local`を常に`true`固定のため、連合サーバー一覧の`note_count`集計テストには
/// 使えない)。
async fn seed_remote_note(db: &PgPool, actor_id: Uuid) -> Uuid {
    let id = Uuid::new_v4();
    let ap_id = format!("https://remote.example/notes/{id}");
    sqlx::query(
        r#"
        INSERT INTO notes (
            id, ap_id, actor_id, content, visibility, sensitive, "to", cc, published,
            replies_count, reactions_count, renotes_count, local, is_poll, poll_multiple, is_talk
        ) VALUES (
            $1, $2, $3, 'remote note', 'public', false, '[]'::jsonb, '[]'::jsonb, now(),
            0, 0, 0, false, false, false, false
        )
        "#,
    )
    .bind(id)
    .bind(&ap_id)
    .bind(actor_id)
    .execute(db)
    .await
    .unwrap();
    id
}

#[tokio::test]
async fn admin_federation_unauthenticated_returns_401() {
    let (app, _db) = test_app_with_db().await;
    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/federation")
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn admin_federation_forbidden_for_plain_user() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let (_uid, session_id) = seed_role_session(&db, &redis, "plainfed", "user").await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/federation")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn admin_federation_requires_federation_permission_not_users() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let role_name = format!("usersonlyfed{}", Uuid::new_v4().simple());
    seed_role(&db, &role_name, false, json!({ "users": true })).await;
    let (_uid, session_id) = seed_role_session(&db, &redis, "usersonlyfedmod", &role_name).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/federation")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn admin_federation_list_empty() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let domain = format!("nomatch-{}.example", Uuid::new_v4().simple());

    let req = Request::builder()
        .method("GET")
        .uri(format!("/api/v1/admin/federation?search={domain}"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let data = body_json(resp).await;
    assert_eq!(data["servers"], json!([]));
    assert_eq!(data["total"], 0);
}

#[tokio::test]
async fn admin_federation_list_with_remote_actors_and_note_count() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let suffix = Uuid::new_v4().simple().to_string();
    let misskey = format!("misskey-{suffix}.example");
    let mastodon = format!("mastodon-{suffix}.example");

    let actor1 = seed_remote_actor(&db, "user1", &misskey).await;
    seed_remote_actor(&db, "user2", &misskey).await;
    let actor3 = seed_remote_actor(&db, "user3", &mastodon).await;
    seed_remote_note(&db, actor1).await;
    seed_remote_note(&db, actor3).await;

    let req = Request::builder()
        .method("GET")
        .uri(format!("/api/v1/admin/federation?search={suffix}"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let data = body_json(resp).await;
    assert_eq!(data["total"], 2);

    let servers = data["servers"].as_array().unwrap();
    let misskey_row = servers
        .iter()
        .find(|s| s["domain"] == json!(misskey))
        .unwrap();
    assert_eq!(misskey_row["user_count"], 2);
    assert_eq!(misskey_row["note_count"], 1);
    assert_eq!(misskey_row["status"], "active");
    assert_eq!(misskey_row["delivery_stats"]["success"], 0);
}

#[tokio::test]
async fn admin_federation_list_status_filter() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let suffix = Uuid::new_v4().simple().to_string();
    let good = format!("good-{suffix}.example");
    let blocked = format!("blocked-{suffix}.example");

    seed_remote_actor(&db, "u1", &good).await;
    seed_remote_actor(&db, "u2", &blocked).await;
    seed_domain_block_full(&db, &blocked, "suspend", None).await;

    let req = Request::builder()
        .method("GET")
        .uri(format!(
            "/api/v1/admin/federation?search={suffix}&status=active"
        ))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.clone().oneshot(req).await.unwrap();
    let data = body_json(resp).await;
    assert_eq!(data["total"], 1);
    assert_eq!(data["servers"][0]["domain"], json!(good));

    let req = Request::builder()
        .method("GET")
        .uri(format!(
            "/api/v1/admin/federation?search={suffix}&status=suspended"
        ))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    let data = body_json(resp).await;
    assert_eq!(data["total"], 1);
    assert_eq!(data["servers"][0]["domain"], json!(blocked));
    assert_eq!(data["servers"][0]["status"], "suspended");
}

#[tokio::test]
async fn admin_federation_list_silenced_filter() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let suffix = Uuid::new_v4().simple().to_string();
    let good = format!("good2-{suffix}.example");
    let quiet = format!("quiet-{suffix}.example");

    seed_remote_actor(&db, "u1", &good).await;
    seed_remote_actor(&db, "u2", &quiet).await;
    seed_domain_block_full(&db, &quiet, "silence", Some("noisy")).await;

    let req = Request::builder()
        .method("GET")
        .uri(format!(
            "/api/v1/admin/federation?search={suffix}&status=silenced"
        ))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    let data = body_json(resp).await;
    assert_eq!(data["total"], 1);
    assert_eq!(data["servers"][0]["domain"], json!(quiet));
    assert_eq!(data["servers"][0]["status"], "silenced");
    assert_eq!(data["servers"][0]["block_severity"], "silence");
}

#[tokio::test]
async fn admin_federation_list_sort_domain_asc_and_desc() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let suffix = Uuid::new_v4().simple().to_string();
    let beta = format!("beta-{suffix}.example");
    let alpha = format!("alpha-{suffix}.example");
    let gamma = format!("gamma-{suffix}.example");

    seed_remote_actor(&db, "u1", &beta).await;
    seed_remote_actor(&db, "u2", &alpha).await;
    seed_remote_actor(&db, "u3", &gamma).await;

    let req = Request::builder()
        .method("GET")
        .uri(format!(
            "/api/v1/admin/federation?search={suffix}&sort=domain&order=asc"
        ))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.clone().oneshot(req).await.unwrap();
    let data = body_json(resp).await;
    let domains: Vec<String> = data["servers"]
        .as_array()
        .unwrap()
        .iter()
        .map(|s| s["domain"].as_str().unwrap().to_string())
        .collect();
    assert_eq!(domains, vec![alpha.clone(), beta.clone(), gamma.clone()]);

    let req = Request::builder()
        .method("GET")
        .uri(format!(
            "/api/v1/admin/federation?search={suffix}&sort=domain&order=desc"
        ))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    let data = body_json(resp).await;
    let domains_desc: Vec<String> = data["servers"]
        .as_array()
        .unwrap()
        .iter()
        .map(|s| s["domain"].as_str().unwrap().to_string())
        .collect();
    assert_eq!(domains_desc, vec![gamma, beta, alpha]);
}

#[tokio::test]
async fn admin_federation_list_pagination() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let suffix = Uuid::new_v4().simple().to_string();
    let mut domains = Vec::new();
    for i in 0..5 {
        let domain = format!("d{i}-{suffix}.example");
        seed_remote_actor(&db, &format!("u{i}"), &domain).await;
        domains.push(domain);
    }
    domains.sort();

    let req = Request::builder()
        .method("GET")
        .uri(format!(
            "/api/v1/admin/federation?search={suffix}&limit=2&offset=0&sort=domain&order=asc"
        ))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.clone().oneshot(req).await.unwrap();
    let data = body_json(resp).await;
    assert_eq!(data["total"], 5);
    let page1 = data["servers"].as_array().unwrap();
    assert_eq!(page1.len(), 2);
    assert_eq!(page1[0]["domain"], json!(domains[0]));
    assert_eq!(page1[1]["domain"], json!(domains[1]));

    let req = Request::builder()
        .method("GET")
        .uri(format!(
            "/api/v1/admin/federation?search={suffix}&limit=2&offset=4&sort=domain&order=asc"
        ))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    let data = body_json(resp).await;
    assert_eq!(data["servers"].as_array().unwrap().len(), 1);
}

#[tokio::test]
async fn admin_federation_list_limit_out_of_range_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/federation?limit=201")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_federation_list_invalid_sort_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/federation?sort=bogus")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_federation_list_delivery_stats() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let domain = format!("target-{}.example", Uuid::new_v4().simple());
    let actor = seed_remote_actor(&db, "u1", &domain).await;

    let inbox = format!("https://{domain}/inbox");
    for _ in 0..3 {
        seed_delivery_job(&db, actor, &inbox, "delivered").await;
    }
    seed_delivery_job(&db, actor, &inbox, "dead").await;
    for _ in 0..2 {
        seed_delivery_job(&db, actor, &inbox, "pending").await;
    }

    let req = Request::builder()
        .method("GET")
        .uri(format!("/api/v1/admin/federation?search={domain}"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    let data = body_json(resp).await;
    let srv = &data["servers"][0];
    assert_eq!(srv["domain"], json!(domain));
    assert_eq!(srv["delivery_stats"]["success"], 3);
    assert_eq!(srv["delivery_stats"]["dead"], 1);
    assert_eq!(srv["delivery_stats"]["pending"], 2);
}

#[tokio::test]
async fn admin_federation_detail_happy_path() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let domain = format!("detail-{}.example", Uuid::new_v4().simple());
    let actor = seed_remote_actor(&db, "testuser", &domain).await;
    seed_remote_note(&db, actor).await;

    let req = Request::builder()
        .method("GET")
        .uri(format!("/api/v1/admin/federation/{domain}"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let data = body_json(resp).await;
    assert_eq!(data["domain"], json!(domain));
    assert_eq!(data["user_count"], 1);
    assert_eq!(data["note_count"], 1);
    assert_eq!(data["status"], "active");
    let actors = data["recent_actors"].as_array().unwrap();
    assert_eq!(actors.len(), 1);
    assert_eq!(actors[0]["username"], "testuser");
}

#[tokio::test]
async fn admin_federation_detail_with_block_info() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let domain = format!("bad-{}.example", Uuid::new_v4().simple());
    seed_remote_actor(&db, "u1", &domain).await;
    seed_domain_block_full(&db, &domain, "suspend", Some("spam server")).await;

    let req = Request::builder()
        .method("GET")
        .uri(format!("/api/v1/admin/federation/{domain}"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    let data = body_json(resp).await;
    assert_eq!(data["status"], "suspended");
    assert_eq!(data["block_severity"], "suspend");
    assert_eq!(data["block_reason"], "spam server");
}

#[tokio::test]
async fn admin_federation_detail_not_found() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("GET")
        .uri(format!(
            "/api/v1/admin/federation/nonexistent-{}.example",
            Uuid::new_v4().simple()
        ))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);
}
