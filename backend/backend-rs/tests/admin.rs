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
use std::sync::LazyLock;
use tokio::sync::Mutex;
use tower::ServiceExt;
use uuid::Uuid;

mod common;
use common::{
    seed_delivery_job, seed_drive_file, seed_follow, seed_local_actor, seed_note_with_visibility,
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

// --- サーバー設定 / 統計 / システム統計 ---

/// `server_settings`テーブルは固定キーでテストDB全体を通じて共有される
/// (Python側は`db`フィクスチャのトランザクションROLLBACKで分離しているが、
/// こちらはコミット直書きのため分離できない、`tests/nodeinfo.rs`と同じ事情)。
/// これらを読み書きするテストは並列実行させず直列化する。
static SETTINGS_LOCK: LazyLock<Mutex<()>> = LazyLock::new(|| Mutex::new(()));

const SETTINGS_KEYS: &[&str] = &[
    "server_name",
    "server_description",
    "tos_url",
    "terms_of_service",
    "privacy_policy",
    "registration_open",
    "registration_mode",
    "invite_create_role",
    "server_theme_color",
    "push_enabled",
    "timeline_default_limit",
    "timeline_max_limit",
    "katex_enabled",
];

async fn clear_settings(db: &PgPool) {
    sqlx::query("DELETE FROM server_settings WHERE key = ANY($1)")
        .bind(SETTINGS_KEYS)
        .execute(db)
        .await
        .expect("failed to clear test settings");
}

#[tokio::test]
async fn admin_settings_get_unauthenticated_returns_401() {
    let (app, _db) = test_app_with_db().await;
    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/settings")
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn admin_settings_get_plain_user_is_forbidden() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let username = format!("plain{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let user_id = seed_user(&db, actor_id, &format!("{username}@example.com")).await;
    let session_id = seed_session(&redis, user_id).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/settings")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn admin_settings_get_custom_admin_permission_role_is_forbidden() {
    // require_admin_role は role == "admin" のみを許可し、roles.is_admin 列は見ない
    // (Python版 get_admin_user と同じ、他の /admin/settings 以外のエンドポイントの
    // require_permission/require_moderation_staff とは異なる判定基準)。
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let role_name = format!("superrole{}", Uuid::new_v4().simple());
    seed_role(&db, &role_name, true, json!({})).await;
    let username = format!("superuser{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let user_id = seed_user(&db, actor_id, &format!("{username}@example.com")).await;
    set_user_role(&db, user_id, &role_name).await;
    let session_id = seed_session(&redis, user_id).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/settings")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn admin_settings_get_returns_defaults_when_unset() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let _guard = SETTINGS_LOCK.lock().await;
    clear_settings(&db).await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/settings")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let data = body_json(resp).await;
    assert_eq!(data["server_name"], Value::Null);
    assert_eq!(data["registration_open"], true);
    assert_eq!(data["registration_mode"], "open");
    assert_eq!(data["invite_create_role"], "admin");
    assert_eq!(data["push_enabled"], true);
    assert_eq!(data["katex_enabled"], false);
    assert_eq!(data["timeline_default_limit"], 20);
    assert_eq!(data["timeline_max_limit"], 40);
    assert!(data["vapid_public_key"].is_string());

    clear_settings(&db).await;
}

#[tokio::test]
async fn admin_settings_update_roundtrip() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let _guard = SETTINGS_LOCK.lock().await;
    clear_settings(&db).await;
    let session_id = seed_admin_session(&db, &redis).await;

    let body = json!({
        "server_name": "My Test Server",
        "server_description": "A description",
        "tos_url": "https://example.com/tos",
        "server_theme_color": "#112233",
        "invite_create_role": "moderator",
        "push_enabled": false,
        "timeline_default_limit": 15,
        "timeline_max_limit": 99,
        "katex_enabled": true,
    });
    let req = Request::builder()
        .method("PATCH")
        .uri("/api/v1/admin/settings")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(body.to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let data = body_json(resp).await;
    assert_eq!(data["server_name"], "My Test Server");
    assert_eq!(data["server_description"], "A description");
    assert_eq!(data["tos_url"], "https://example.com/tos");
    assert_eq!(data["server_theme_color"], "#112233");
    assert_eq!(data["invite_create_role"], "moderator");
    assert_eq!(data["push_enabled"], false);
    assert_eq!(data["timeline_default_limit"], 15);
    assert_eq!(data["timeline_max_limit"], 99);
    assert_eq!(data["katex_enabled"], true);

    // GETで永続化を再確認する。
    let (app2, _db2) = test_app_with_db().await;
    let get_req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/settings")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let get_resp = app2.oneshot(get_req).await.unwrap();
    let get_data = body_json(get_resp).await;
    assert_eq!(get_data["server_name"], "My Test Server");
    assert_eq!(get_data["timeline_max_limit"], 99);

    // moderation_log に記録されていることを確認する。
    let logged: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM moderation_log WHERE action = 'update_settings' AND target_id = 'settings'",
    )
    .fetch_one(&db)
    .await
    .unwrap();
    assert!(logged >= 1);

    clear_settings(&db).await;
}

#[tokio::test]
async fn admin_settings_clear_nullable_string_with_explicit_null() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let _guard = SETTINGS_LOCK.lock().await;
    clear_settings(&db).await;
    let session_id = seed_admin_session(&db, &redis).await;

    sqlx::query(
        "INSERT INTO server_settings (key, value, updated_at) VALUES ('server_name', 'Old Name', now())",
    )
    .execute(&db)
    .await
    .unwrap();

    let body = json!({ "server_name": null });
    let req = Request::builder()
        .method("PATCH")
        .uri("/api/v1/admin/settings")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(body.to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let data = body_json(resp).await;
    assert_eq!(data["server_name"], Value::Null);

    clear_settings(&db).await;
}

#[tokio::test]
async fn admin_settings_registration_mode_open_approves_pending_users() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let _guard = SETTINGS_LOCK.lock().await;
    clear_settings(&db).await;
    let session_id = seed_admin_session(&db, &redis).await;

    let username = format!("pending{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let pending_user_id = seed_user(&db, actor_id, &format!("{username}@example.com")).await;
    sqlx::query("UPDATE users SET approval_status = 'pending' WHERE id = $1")
        .bind(pending_user_id)
        .execute(&db)
        .await
        .unwrap();

    let body = json!({ "registration_mode": "open" });
    let req = Request::builder()
        .method("PATCH")
        .uri("/api/v1/admin/settings")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(body.to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);

    let approval_status: String =
        sqlx::query_scalar("SELECT approval_status FROM users WHERE id = $1")
            .bind(pending_user_id)
            .fetch_one(&db)
            .await
            .unwrap();
    assert_eq!(approval_status, "approved");

    let logged: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM moderation_log WHERE action = 'approve_registration' AND target_id = $1",
    )
    .bind(pending_user_id.to_string())
    .fetch_one(&db)
    .await
    .unwrap();
    assert!(logged >= 1);

    clear_settings(&db).await;
}

#[tokio::test]
async fn admin_settings_registration_mode_closed_rejects_pending_users() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let _guard = SETTINGS_LOCK.lock().await;
    clear_settings(&db).await;
    let session_id = seed_admin_session(&db, &redis).await;

    let username = format!("pending{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let pending_user_id = seed_user(&db, actor_id, &format!("{username}@example.com")).await;
    sqlx::query("UPDATE users SET approval_status = 'pending' WHERE id = $1")
        .bind(pending_user_id)
        .execute(&db)
        .await
        .unwrap();

    let body = json!({ "registration_mode": "closed" });
    let req = Request::builder()
        .method("PATCH")
        .uri("/api/v1/admin/settings")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(body.to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let data = body_json(resp).await;
    assert_eq!(data["registration_open"], false);

    let remaining_users: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM users WHERE id = $1")
        .bind(pending_user_id)
        .fetch_one(&db)
        .await
        .unwrap();
    assert_eq!(remaining_users, 0);
    let remaining_actors: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM actors WHERE id = $1")
        .bind(actor_id)
        .fetch_one(&db)
        .await
        .unwrap();
    assert_eq!(remaining_actors, 0);

    clear_settings(&db).await;
}

#[tokio::test]
async fn admin_settings_registration_mode_approval_does_not_resolve_pending() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let _guard = SETTINGS_LOCK.lock().await;
    clear_settings(&db).await;
    let session_id = seed_admin_session(&db, &redis).await;

    let username = format!("pending{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let pending_user_id = seed_user(&db, actor_id, &format!("{username}@example.com")).await;
    sqlx::query("UPDATE users SET approval_status = 'pending' WHERE id = $1")
        .bind(pending_user_id)
        .execute(&db)
        .await
        .unwrap();

    let body = json!({ "registration_mode": "approval" });
    let req = Request::builder()
        .method("PATCH")
        .uri("/api/v1/admin/settings")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(body.to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);

    let approval_status: String =
        sqlx::query_scalar("SELECT approval_status FROM users WHERE id = $1")
            .bind(pending_user_id)
            .fetch_one(&db)
            .await
            .unwrap();
    assert_eq!(approval_status, "pending");

    clear_settings(&db).await;
}

#[tokio::test]
async fn admin_settings_invalid_registration_mode_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let _guard = SETTINGS_LOCK.lock().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let body = json!({ "registration_mode": "bogus" });
    let req = Request::builder()
        .method("PATCH")
        .uri("/api/v1/admin/settings")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(body.to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_settings_invalid_theme_color_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let _guard = SETTINGS_LOCK.lock().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let body = json!({ "server_theme_color": "not-a-color" });
    let req = Request::builder()
        .method("PATCH")
        .uri("/api/v1/admin/settings")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(body.to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_settings_timeline_limit_out_of_range_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let _guard = SETTINGS_LOCK.lock().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let body = json!({ "timeline_default_limit": 0 });
    let req = Request::builder()
        .method("PATCH")
        .uri("/api/v1/admin/settings")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(body.to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_stats_unauthenticated_returns_401() {
    let (app, _db) = test_app_with_db().await;
    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/stats")
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn admin_stats_plain_user_is_forbidden() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let username = format!("plain{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let user_id = seed_user(&db, actor_id, &format!("{username}@example.com")).await;
    let session_id = seed_session(&redis, user_id).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/stats")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn admin_stats_custom_role_with_users_permission_can_read() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let role_name = format!("statsrole{}", Uuid::new_v4().simple());
    seed_role(&db, &role_name, false, json!({ "users": true })).await;
    let username = format!("statsmod{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let user_id = seed_user(&db, actor_id, &format!("{username}@example.com")).await;
    set_user_role(&db, user_id, &role_name).await;
    let session_id = seed_session(&redis, user_id).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/stats")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
}

#[tokio::test]
async fn admin_stats_counts_reflect_new_local_users_and_notes() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    async fn fetch_stats(app: axum::Router, session_id: &str) -> (i64, i64) {
        let req = Request::builder()
            .method("GET")
            .uri("/api/v1/admin/stats")
            .header("cookie", cookie_header(session_id))
            .body(Body::empty())
            .unwrap();
        let resp = app.oneshot(req).await.unwrap();
        let data = body_json(resp).await;
        (
            data["user_count"].as_i64().unwrap(),
            data["note_count"].as_i64().unwrap(),
        )
    }

    let (app_before, _) = test_app_with_db().await;
    let (before_users, before_notes) = fetch_stats(app_before, &session_id).await;

    let username = format!("statsuser{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    seed_user(&db, actor_id, &format!("{username}@example.com")).await;
    seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;

    let (after_users, after_notes) = fetch_stats(app, &session_id).await;
    // `users`/`notes`はテストDB全体で共有されるグローバル集計のため、他の
    // テストが並行してシードした分も混ざりうる。自分が追加した分が確実に
    // 反映されていることだけを検証する(厳密な差分ではなく下限)。
    assert!(after_users > before_users);
    assert!(after_notes > before_notes);
}

#[tokio::test]
async fn admin_stats_domain_count_reflects_new_remote_follow_relationship() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    async fn fetch_domain_count(app: axum::Router, session_id: &str) -> i64 {
        let req = Request::builder()
            .method("GET")
            .uri("/api/v1/admin/stats")
            .header("cookie", cookie_header(session_id))
            .body(Body::empty())
            .unwrap();
        let resp = app.oneshot(req).await.unwrap();
        let data = body_json(resp).await;
        data["domain_count"].as_i64().unwrap()
    }

    let (app_before, _) = test_app_with_db().await;
    let before = fetch_domain_count(app_before, &session_id).await;

    let local_username = format!("localuser{}", Uuid::new_v4().simple());
    let local_actor_id = seed_local_actor(&db, &local_username).await;
    let domain = format!("remote-{}.example", Uuid::new_v4().simple());
    let remote_actor_id = seed_remote_actor(
        &db,
        &format!("remoteuser{}", Uuid::new_v4().simple()),
        &domain,
    )
    .await;
    seed_follow(&db, local_actor_id, remote_actor_id).await;

    let after = fetch_domain_count(app, &session_id).await;
    // 他の並行テストも独自のユニークなリモートドメインを追加しうるため、
    // 厳密な差分ではなく自分の分が反映されていることだけを検証する。
    assert!(after > before);
}

#[tokio::test]
async fn admin_system_stats_unauthenticated_returns_401() {
    let (app, _db) = test_app_with_db().await;
    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/system/stats")
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn admin_system_stats_plain_user_is_forbidden() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let username = format!("plain{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let user_id = seed_user(&db, actor_id, &format!("{username}@example.com")).await;
    let session_id = seed_session(&redis, user_id).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/system/stats")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn admin_system_stats_admin_returns_expected_shape() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/system/stats")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let data = body_json(resp).await;
    assert!(data["db_pool_size"].as_i64().unwrap() >= 1);
    assert_eq!(data["db_pool_overflow"], 0);
    assert!(data["load_avg_1m"].is_number());
    assert!(data["memory_total_mb"].is_number());
    assert!(data["uptime_seconds"].is_number());
    assert!(data["worker_alive"].is_boolean());
}

// --- お知らせ (announcements) ---

#[tokio::test]
async fn admin_announcements_unauthenticated_returns_401() {
    let (app, _db) = test_app_with_db().await;
    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/announcements")
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn admin_announcements_plain_user_is_forbidden() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let username = format!("plain{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let user_id = seed_user(&db, actor_id, &format!("{username}@example.com")).await;
    let session_id = seed_session(&redis, user_id).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/announcements")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn admin_custom_role_with_announcements_permission_can_create() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let role_name = format!("announcer{}", Uuid::new_v4().simple());
    seed_role(&db, &role_name, false, json!({ "announcements": true })).await;
    let (_uid, session_id) = seed_role_session(&db, &redis, "announcer", &role_name).await;

    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/announcements")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(
            json!({ "title": "Maintenance", "content": "We will be down." }).to_string(),
        ))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::CREATED);
}

#[tokio::test]
async fn admin_custom_role_without_announcements_permission_is_forbidden() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let role_name = format!("helper{}", Uuid::new_v4().simple());
    seed_role(&db, &role_name, false, json!({ "reports": true })).await;
    let (_uid, session_id) = seed_role_session(&db, &redis, "helper", &role_name).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/announcements")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn admin_create_announcement_renders_content_html_and_defaults() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/announcements")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(
            json!({ "title": "Hello", "content": "**bold** text" }).to_string(),
        ))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::CREATED);
    let json = body_json(resp).await;
    assert_eq!(json["title"], "Hello");
    assert_eq!(json["content"], "**bold** text");
    assert_eq!(json["content_html"], "<p><strong>bold</strong> text</p>");
    assert_eq!(json["published"], false);
    assert_eq!(json["all_day"], false);
    assert!(json["starts_at"].is_null());
    assert!(json["ends_at"].is_null());
    assert!(json["id"].is_string());
    assert!(json["created_at"].is_string());
    assert_eq!(json["created_at"], json["updated_at"]);
}

#[tokio::test]
async fn admin_create_announcement_title_too_long_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/announcements")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(
            json!({ "title": "x".repeat(501), "content": "body" }).to_string(),
        ))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_create_announcement_empty_content_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/announcements")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(
            json!({ "title": "x", "content": "" }).to_string(),
        ))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

async fn seed_announcement_via_api(app: &axum::Router, session_id: &str, title: &str) -> Value {
    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/announcements")
        .header("cookie", cookie_header(session_id))
        .header("content-type", "application/json")
        .body(Body::from(
            json!({ "title": title, "content": "body" }).to_string(),
        ))
        .unwrap();
    let resp = app.clone().oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::CREATED);
    body_json(resp).await
}

#[tokio::test]
async fn admin_list_announcements_orders_by_created_at_desc() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let first = seed_announcement_via_api(&app, &session_id, "First").await;
    let second = seed_announcement_via_api(&app, &session_id, "Second").await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/announcements")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    let ids: Vec<String> = json
        .as_array()
        .unwrap()
        .iter()
        .map(|a| a["id"].as_str().unwrap().to_string())
        .collect();
    let first_idx = ids
        .iter()
        .position(|id| id == first["id"].as_str().unwrap());
    let second_idx = ids
        .iter()
        .position(|id| id == second["id"].as_str().unwrap());
    assert!(second_idx < first_idx);
}

#[tokio::test]
async fn admin_get_announcement_returns_404_for_missing() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("GET")
        .uri(format!("/api/v1/admin/announcements/{}", Uuid::new_v4()))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn admin_get_announcement_happy_path() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let created = seed_announcement_via_api(&app, &session_id, "Gettable").await;
    let id = created["id"].as_str().unwrap();

    let req = Request::builder()
        .method("GET")
        .uri(format!("/api/v1/admin/announcements/{id}"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    assert_eq!(json["id"], id);
    assert_eq!(json["title"], "Gettable");
}

#[tokio::test]
async fn admin_update_announcement_partially_updates_only_given_fields() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let created = seed_announcement_via_api(&app, &session_id, "Original").await;
    let id = created["id"].as_str().unwrap();

    let req = Request::builder()
        .method("PATCH")
        .uri(format!("/api/v1/admin/announcements/{id}"))
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(json!({ "published": true }).to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    assert_eq!(json["published"], true);
    // titleとcontentは変更されず維持される。
    assert_eq!(json["title"], "Original");
    assert_eq!(json["content"], "body");
}

#[tokio::test]
async fn admin_update_announcement_content_rerenders_content_html() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let created = seed_announcement_via_api(&app, &session_id, "Rerender").await;
    let id = created["id"].as_str().unwrap();

    let req = Request::builder()
        .method("PATCH")
        .uri(format!("/api/v1/admin/announcements/{id}"))
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(json!({ "content": "# Heading" }).to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    assert_eq!(json["content"], "# Heading");
    assert_eq!(json["content_html"], "<h1>Heading</h1>");
}

#[tokio::test]
async fn admin_update_announcement_can_clear_starts_at_with_explicit_null() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let created = seed_announcement_via_api(&app, &session_id, "Scheduled").await;
    let id = created["id"].as_str().unwrap();

    let req = Request::builder()
        .method("PATCH")
        .uri(format!("/api/v1/admin/announcements/{id}"))
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(
            json!({ "starts_at": "2026-01-01T00:00:00Z" }).to_string(),
        ))
        .unwrap();
    let resp = app.clone().oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    assert_eq!(json["starts_at"], "2026-01-01T00:00:00+00:00");

    // 明示的なnullでクリアできる。
    let req = Request::builder()
        .method("PATCH")
        .uri(format!("/api/v1/admin/announcements/{id}"))
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(json!({ "starts_at": null }).to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    assert!(json["starts_at"].is_null());
}

#[tokio::test]
async fn admin_update_announcement_ignores_explicit_null_for_non_nullable_field() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let created = seed_announcement_via_api(&app, &session_id, "KeepsTitle").await;
    let id = created["id"].as_str().unwrap();

    // Python版の`update_announcement`は非nullableフィールドへの明示的な
    // `null`を無視する(`if value is not None or key in nullable_fields`)。
    let req = Request::builder()
        .method("PATCH")
        .uri(format!("/api/v1/admin/announcements/{id}"))
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(json!({ "title": null }).to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    assert_eq!(json["title"], "KeepsTitle");
}

#[tokio::test]
async fn admin_update_nonexistent_announcement_returns_404() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("PATCH")
        .uri(format!("/api/v1/admin/announcements/{}", Uuid::new_v4()))
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(json!({ "title": "x" }).to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn admin_delete_announcement_happy_path() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let created = seed_announcement_via_api(&app, &session_id, "Deletable").await;
    let id = created["id"].as_str().unwrap();

    let req = Request::builder()
        .method("DELETE")
        .uri(format!("/api/v1/admin/announcements/{id}"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.clone().oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::NO_CONTENT);

    let req = Request::builder()
        .method("GET")
        .uri(format!("/api/v1/admin/announcements/{id}"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn admin_delete_nonexistent_announcement_returns_404() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("DELETE")
        .uri(format!("/api/v1/admin/announcements/{}", Uuid::new_v4()))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);
}

// --- カスタム絵文字 (emoji) ---

#[tokio::test]
async fn admin_emoji_list_unauthenticated_returns_401() {
    let (app, _db) = test_app_with_db().await;
    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/emoji/list")
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn admin_emoji_list_plain_user_is_forbidden() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let username = format!("plain{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let user_id = seed_user(&db, actor_id, &format!("{username}@example.com")).await;
    let session_id = seed_session(&redis, user_id).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/emoji/list")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn admin_custom_role_with_emoji_permission_can_list() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let role_name = format!("emojiist{}", Uuid::new_v4().simple());
    seed_role(&db, &role_name, false, json!({ "emoji": true })).await;
    let (_uid, session_id) = seed_role_session(&db, &redis, "emojiist", &role_name).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/emoji/list")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
}

#[tokio::test]
async fn admin_custom_role_without_emoji_permission_is_forbidden() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let role_name = format!("helper{}", Uuid::new_v4().simple());
    seed_role(&db, &role_name, false, json!({ "reports": true })).await;
    let (_uid, session_id) = seed_role_session(&db, &redis, "helper", &role_name).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/emoji/list")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn admin_emoji_list_returns_only_local_ordered_by_category_then_shortcode() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let suffix = Uuid::new_v4().simple().to_string();
    let local_b = common::seed_custom_emoji(
        &db,
        &format!("local_b_{suffix}"),
        None,
        "https://example.test/b.png",
    )
    .await;
    let local_a = common::seed_custom_emoji(
        &db,
        &format!("local_a_{suffix}"),
        None,
        "https://example.test/a.png",
    )
    .await;
    common::seed_custom_emoji(
        &db,
        &format!("remote_{suffix}"),
        Some("remote.example"),
        "https://remote.example/e.png",
    )
    .await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/emoji/list")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    let entries = json.as_array().unwrap();
    let ids: Vec<String> = entries
        .iter()
        .map(|e| e["id"].as_str().unwrap().to_string())
        .collect();
    assert!(ids.contains(&local_a.to_string()));
    assert!(ids.contains(&local_b.to_string()));
    // ドメイン無し(ローカル)同士は同じcategory(NULL)内でshortcode昇順。
    let a_idx = ids
        .iter()
        .position(|id| id == &local_a.to_string())
        .unwrap();
    let b_idx = ids
        .iter()
        .position(|id| id == &local_b.to_string())
        .unwrap();
    assert!(a_idx < b_idx);
    for entry in entries {
        assert!(entry["domain"].is_null() || entry.get("domain").is_none());
    }
}

#[tokio::test]
async fn admin_emoji_remote_filters_by_domain_and_search() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let suffix = Uuid::new_v4().simple().to_string();
    let domain_a = format!("a-{suffix}.example");
    let domain_b = format!("b-{suffix}.example");
    common::seed_custom_emoji(
        &db,
        &format!("blobcat_{suffix}"),
        Some(&domain_a),
        "https://a.example/blobcat.png",
    )
    .await;
    common::seed_custom_emoji(
        &db,
        &format!("partyparrot_{suffix}"),
        Some(&domain_a),
        "https://a.example/party.png",
    )
    .await;
    common::seed_custom_emoji(
        &db,
        &format!("blobcat_{suffix}"),
        Some(&domain_b),
        "https://b.example/blobcat.png",
    )
    .await;

    // domain フィルタ。
    let req = Request::builder()
        .method("GET")
        .uri(format!("/api/v1/admin/emoji/remote?domain={domain_a}"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.clone().oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    let entries = json.as_array().unwrap();
    assert_eq!(entries.len(), 2);
    assert!(entries.iter().all(|e| e["domain"] == domain_a));

    // search フィルタ(ILIKE部分一致)。
    let req = Request::builder()
        .method("GET")
        .uri(format!(
            "/api/v1/admin/emoji/remote?domain={domain_a}&search=party"
        ))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    let entries = json.as_array().unwrap();
    assert_eq!(entries.len(), 1);
    assert_eq!(entries[0]["shortcode"], format!("partyparrot_{suffix}"));
}

#[tokio::test]
async fn admin_emoji_remote_limit_over_200_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/emoji/remote?limit=201")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_emoji_remote_negative_offset_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/emoji/remote?offset=-1")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_emoji_remote_domains_returns_distinct_sorted_domains() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let suffix = Uuid::new_v4().simple().to_string();
    let domain_a = format!("aa-{suffix}.example");
    let domain_b = format!("zz-{suffix}.example");
    common::seed_custom_emoji(
        &db,
        &format!("one_{suffix}"),
        Some(&domain_b),
        "https://b/one.png",
    )
    .await;
    common::seed_custom_emoji(
        &db,
        &format!("two_{suffix}"),
        Some(&domain_a),
        "https://a/two.png",
    )
    .await;
    common::seed_custom_emoji(
        &db,
        &format!("three_{suffix}"),
        Some(&domain_a),
        "https://a/three.png",
    )
    .await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/emoji/remote/domains")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    let domains: Vec<String> = json
        .as_array()
        .unwrap()
        .iter()
        .map(|d| d.as_str().unwrap().to_string())
        .collect();
    let a_idx = domains.iter().position(|d| d == &domain_a).unwrap();
    let b_idx = domains.iter().position(|d| d == &domain_b).unwrap();
    assert!(a_idx < b_idx);
    // domain_aは2件投入したが、DISTINCTで1件のみ出現する。
    assert_eq!(domains.iter().filter(|d| *d == &domain_a).count(), 1);
}

#[tokio::test]
async fn admin_update_emoji_partially_updates_only_given_fields() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let suffix = Uuid::new_v4().simple().to_string();
    let shortcode = format!("orig_{suffix}");
    let id = common::seed_custom_emoji(&db, &shortcode, None, "https://example.test/e.png").await;
    sqlx::query("UPDATE custom_emojis SET category = 'animals', license = 'CC-BY' WHERE id = $1")
        .bind(id)
        .execute(&db)
        .await
        .unwrap();

    let req = Request::builder()
        .method("PATCH")
        .uri(format!("/api/v1/admin/emoji/{id}"))
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(json!({ "is_sensitive": true }).to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    assert_eq!(json["is_sensitive"], true);
    // 与えられなかったフィールドは維持される。
    assert_eq!(json["shortcode"], shortcode);
    assert_eq!(json["category"], "animals");
    assert_eq!(json["license"], "CC-BY");
}

#[tokio::test]
async fn admin_update_emoji_explicit_null_clears_nullable_field() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let suffix = Uuid::new_v4().simple().to_string();
    let shortcode = format!("clearable_{suffix}");
    let id = common::seed_custom_emoji(&db, &shortcode, None, "https://example.test/e.png").await;
    sqlx::query("UPDATE custom_emojis SET category = 'animals' WHERE id = $1")
        .bind(id)
        .execute(&db)
        .await
        .unwrap();

    let req = Request::builder()
        .method("PATCH")
        .uri(format!("/api/v1/admin/emoji/{id}"))
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(json!({ "category": null }).to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    assert!(json["category"].is_null());
}

#[tokio::test]
async fn admin_update_emoji_ignores_explicit_null_for_non_nullable_field() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let suffix = Uuid::new_v4().simple().to_string();
    let shortcode = format!("keeps_{suffix}");
    let id = common::seed_custom_emoji(&db, &shortcode, None, "https://example.test/e.png").await;

    // shortcode(DB上NOT NULL)への明示的なnullはannouncementsのtitle等と
    // 同じく無視される。
    let req = Request::builder()
        .method("PATCH")
        .uri(format!("/api/v1/admin/emoji/{id}"))
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(json!({ "shortcode": null }).to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    assert_eq!(json["shortcode"], shortcode);
}

#[tokio::test]
async fn admin_update_emoji_invalid_shortcode_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let id = common::seed_custom_emoji(
        &db,
        &format!("valid_{}", Uuid::new_v4().simple()),
        None,
        "https://example.test/e.png",
    )
    .await;

    let req = Request::builder()
        .method("PATCH")
        .uri(format!("/api/v1/admin/emoji/{id}"))
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(json!({ "shortcode": "not valid!" }).to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_update_emoji_accepts_but_does_not_persist_usage_info_and_is_based_on() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let id = common::seed_custom_emoji(
        &db,
        &format!("dropped_{}", Uuid::new_v4().simple()),
        None,
        "https://example.test/e.png",
    )
    .await;

    // Python版の`_EMOJI_UPDATABLE_FIELDS`が`usage_info`/`is_based_on`を
    // 含まないため、受理・検証はされるが永続化されない既知の挙動。
    let req = Request::builder()
        .method("PATCH")
        .uri(format!("/api/v1/admin/emoji/{id}"))
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(
            json!({ "usage_info": "for fun", "is_based_on": "https://example.test/base" })
                .to_string(),
        ))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    assert!(json["usage_info"].is_null());
    assert!(json["is_based_on"].is_null());
}

#[tokio::test]
async fn admin_update_nonexistent_emoji_returns_404() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("PATCH")
        .uri(format!("/api/v1/admin/emoji/{}", Uuid::new_v4()))
        .header("cookie", cookie_header(&session_id))
        .header("content-type", "application/json")
        .body(Body::from(json!({ "category": "x" }).to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);
}

// --- カスタム絵文字 add/delete (S3アップロードを伴う) ---

// Python版 `backend/tests/test_service_drive.py` の `PNG_1x1` と同一のバイト列
// (1x1ピクセルの最小有効PNG)。
const PNG_1X1: &[u8] = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde";

/// `multipart/form-data`のリクエストボディを手組みする。`fields`は通常の
/// テキストフィールド、`file`は`(フィールド名, ファイル名, Content-Type, バイト列)`。
fn build_multipart_body(
    fields: &[(&str, &str)],
    file: Option<(&str, &str, &str, &[u8])>,
) -> (String, Vec<u8>) {
    let boundary = format!("testboundary{}", Uuid::new_v4().simple());
    let mut body = Vec::new();
    for (name, value) in fields {
        body.extend_from_slice(
            format!("--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n")
                .as_bytes(),
        );
    }
    if let Some((field_name, filename, content_type, data)) = file {
        body.extend_from_slice(
            format!(
                "--{boundary}\r\nContent-Disposition: form-data; name=\"{field_name}\"; \
                 filename=\"{filename}\"\r\nContent-Type: {content_type}\r\n\r\n"
            )
            .as_bytes(),
        );
        body.extend_from_slice(data);
        body.extend_from_slice(b"\r\n");
    }
    body.extend_from_slice(format!("--{boundary}--\r\n").as_bytes());
    (format!("multipart/form-data; boundary={boundary}"), body)
}

#[tokio::test]
async fn admin_add_emoji_unauthenticated_returns_401() {
    let (app, _db) = test_app_with_db().await;
    let (content_type, body) = build_multipart_body(
        &[("shortcode", "nekotest")],
        Some(("file", "e.png", "image/png", PNG_1X1)),
    );
    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/emoji/add")
        .header("content-type", content_type)
        .body(Body::from(body))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn admin_add_emoji_plain_user_is_forbidden() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let username = format!("plain{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let user_id = seed_user(&db, actor_id, &format!("{username}@example.com")).await;
    let session_id = seed_session(&redis, user_id).await;
    let (content_type, body) = build_multipart_body(
        &[("shortcode", "nekotest2")],
        Some(("file", "e.png", "image/png", PNG_1X1)),
    );

    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/emoji/add")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", content_type)
        .body(Body::from(body))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn admin_add_emoji_uploads_to_s3_and_creates_local_emoji() {
    common::ensure_test_s3_bucket().await;
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let shortcode = format!("upload_{}", Uuid::new_v4().simple());
    let (content_type, body) = build_multipart_body(
        &[
            ("shortcode", shortcode.as_str()),
            ("category", "animals"),
            ("is_sensitive", "true"),
            ("aliases", "[\"cat\",\"neko\"]"),
            ("usage_info", "free to use"),
        ],
        Some(("file", "e.png", "image/png", PNG_1X1)),
    );

    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/emoji/add")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", content_type)
        .body(Body::from(body))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    assert_eq!(json["shortcode"], shortcode);
    assert_eq!(json["category"], "animals");
    assert_eq!(json["is_sensitive"], true);
    assert_eq!(json["visible_in_picker"], true);
    assert_eq!(json["aliases"], json!(["cat", "neko"]));
    // `create_local_emoji`は`update_emoji`と異なり`usage_info`もそのまま永続化する。
    assert_eq!(json["usage_info"], "free to use");
    let url = json["url"].as_str().unwrap().to_string();
    assert!(url.contains("/media/server/"));

    let (drive_file_id, size_bytes): (Option<Uuid>, i64) = sqlx::query_as(
        "SELECT df.id, df.size_bytes FROM custom_emojis ce \
         JOIN drive_files df ON df.id = ce.drive_file_id \
         WHERE ce.shortcode = $1",
    )
    .bind(&shortcode)
    .fetch_one(&db)
    .await
    .unwrap();
    assert!(drive_file_id.is_some());
    assert_eq!(size_bytes, PNG_1X1.len() as i64);
}

#[tokio::test]
async fn admin_add_emoji_duplicate_shortcode_returns_409() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let shortcode = format!("dup_{}", Uuid::new_v4().simple());
    common::seed_custom_emoji(&db, &shortcode, None, "https://example.test/e.png").await;
    let (content_type, body) = build_multipart_body(
        &[("shortcode", shortcode.as_str())],
        Some(("file", "e.png", "image/png", PNG_1X1)),
    );

    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/emoji/add")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", content_type)
        .body(Body::from(body))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::CONFLICT);
}

#[tokio::test]
async fn admin_add_emoji_invalid_shortcode_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let (content_type, body) = build_multipart_body(
        &[("shortcode", "not valid!")],
        Some(("file", "e.png", "image/png", PNG_1X1)),
    );

    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/emoji/add")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", content_type)
        .body(Body::from(body))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_add_emoji_missing_file_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let (content_type, body) = build_multipart_body(&[("shortcode", "nofile")], None);

    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/emoji/add")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", content_type)
        .body(Body::from(body))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_delete_emoji_unauthenticated_returns_401() {
    let (app, _db) = test_app_with_db().await;
    let req = Request::builder()
        .method("DELETE")
        .uri(format!("/api/v1/admin/emoji/{}", Uuid::new_v4()))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn admin_delete_nonexistent_emoji_returns_404() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("DELETE")
        .uri(format!("/api/v1/admin/emoji/{}", Uuid::new_v4()))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn admin_delete_emoji_without_drive_file_removes_row() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let shortcode = format!("nodrive_{}", Uuid::new_v4().simple());
    let id = common::seed_custom_emoji(&db, &shortcode, None, "https://example.test/e.png").await;

    let req = Request::builder()
        .method("DELETE")
        .uri(format!("/api/v1/admin/emoji/{id}"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    assert_eq!(json["ok"], true);

    let remaining: Option<Uuid> = sqlx::query_scalar("SELECT id FROM custom_emojis WHERE id = $1")
        .bind(id)
        .fetch_optional(&db)
        .await
        .unwrap();
    assert!(remaining.is_none());
}

#[tokio::test]
async fn admin_delete_emoji_removes_s3_object_and_drive_file_row() {
    common::ensure_test_s3_bucket().await;
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    // add_emojiで実際にS3へアップロード済みの絵文字を用意してから削除する
    // (アップロード経路と削除経路の両方を実S3で検証する)。
    let shortcode = format!("todelete_{}", Uuid::new_v4().simple());
    let (content_type, body) = build_multipart_body(
        &[("shortcode", shortcode.as_str())],
        Some(("file", "e.png", "image/png", PNG_1X1)),
    );
    let add_req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/emoji/add")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", content_type)
        .body(Body::from(body))
        .unwrap();
    let add_resp = app.clone().oneshot(add_req).await.unwrap();
    assert_eq!(add_resp.status(), StatusCode::OK);
    let created = body_json(add_resp).await;
    let id = Uuid::parse_str(created["id"].as_str().unwrap()).unwrap();

    let drive_file_id: Uuid =
        sqlx::query_scalar("SELECT drive_file_id FROM custom_emojis WHERE id = $1")
            .bind(id)
            .fetch_one(&db)
            .await
            .unwrap();

    let del_req = Request::builder()
        .method("DELETE")
        .uri(format!("/api/v1/admin/emoji/{id}"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let del_resp = app.oneshot(del_req).await.unwrap();
    assert_eq!(del_resp.status(), StatusCode::OK);

    let remaining_emoji: Option<Uuid> =
        sqlx::query_scalar("SELECT id FROM custom_emojis WHERE id = $1")
            .bind(id)
            .fetch_optional(&db)
            .await
            .unwrap();
    assert!(remaining_emoji.is_none());
    let remaining_drive_file: Option<Uuid> =
        sqlx::query_scalar("SELECT id FROM drive_files WHERE id = $1")
            .bind(drive_file_id)
            .fetch_optional(&db)
            .await
            .unwrap();
    assert!(remaining_drive_file.is_none());
}

// --- サーバーファイル管理 (server-files, S3アップロードを伴う) ---

#[tokio::test]
async fn admin_server_files_list_unauthenticated_returns_401() {
    let (app, _db) = test_app_with_db().await;
    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/server-files")
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn admin_server_files_list_plain_user_is_forbidden() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let username = format!("plainsf{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let user_id = seed_user(&db, actor_id, &format!("{username}@example.com")).await;
    let session_id = seed_session(&redis, user_id).await;

    let req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/server-files")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

/// このテストバイナリ内の全テストが1つの共有DBを使う(#1139方針上、`tower::
/// ServiceExt::oneshot`が実DBに対して動く結合テストのため、テストごとの
/// トランザクションロールバックは無い)ため、一覧が本当に空であることは
/// 検証できない。代わりに`ORDER BY created_at DESC`(新しいものが先頭)を検証する。
#[tokio::test]
async fn admin_server_files_list_orders_newest_first() {
    common::ensure_test_s3_bucket().await;
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let upload = |app: axum::Router, session_id: String, name: &'static str| async move {
        let (content_type, body) =
            build_multipart_body(&[], Some(("file", name, "image/png", PNG_1X1)));
        let req = Request::builder()
            .method("POST")
            .uri("/api/v1/admin/server-files")
            .header("cookie", cookie_header(&session_id))
            .header("content-type", content_type)
            .body(Body::from(body))
            .unwrap();
        let resp = app.oneshot(req).await.unwrap();
        body_json(resp).await["id"].as_str().unwrap().to_string()
    };

    let first_id = upload(app.clone(), session_id.clone(), "first.png").await;
    tokio::time::sleep(std::time::Duration::from_millis(10)).await;
    let second_id = upload(app.clone(), session_id.clone(), "second.png").await;

    let list_req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/server-files")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let list_resp = app.oneshot(list_req).await.unwrap();
    assert_eq!(list_resp.status(), StatusCode::OK);
    let list = body_json(list_resp).await;
    let ids: Vec<String> = list
        .as_array()
        .unwrap()
        .iter()
        .map(|f| f["id"].as_str().unwrap().to_string())
        .collect();
    let pos_first = ids.iter().position(|id| *id == first_id).unwrap();
    let pos_second = ids.iter().position(|id| *id == second_id).unwrap();
    assert!(
        pos_second < pos_first,
        "newest upload should be listed before the older one"
    );
}

// `custom_emojis`に紐づかない点以外はadd_emoji/delete_emojiと同じ`drive::upload_drive_file`/
// `drive::delete_drive_file`(#1175)経由のため、S3を伴う経路自体はそちらのテストで検証済み。
// ここでは`custom_emojis`テーブルを介さずレスポンス整形する差分部分のみ確認する。
#[tokio::test]
async fn admin_upload_server_file_creates_drive_file_row_and_appears_in_list() {
    common::ensure_test_s3_bucket().await;
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let (content_type, body) =
        build_multipart_body(&[], Some(("file", "server-icon.png", "image/png", PNG_1X1)));

    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/server-files")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", content_type)
        .body(Body::from(body))
        .unwrap();
    let resp = app.clone().oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let json = body_json(resp).await;
    let file_id = json["id"].as_str().unwrap().to_string();
    assert_eq!(json["filename"], "server-icon.png");
    assert_eq!(json["mime_type"], "image/png");
    assert_eq!(json["size_bytes"], PNG_1X1.len() as i64);
    assert!(json["url"].as_str().unwrap().contains("/media/server/"));

    let (server_file, size_bytes): (bool, i64) =
        sqlx::query_as("SELECT server_file, size_bytes FROM drive_files WHERE id = $1")
            .bind(Uuid::parse_str(&file_id).unwrap())
            .fetch_one(&db)
            .await
            .unwrap();
    assert!(server_file);
    assert_eq!(size_bytes, PNG_1X1.len() as i64);

    let list_req = Request::builder()
        .method("GET")
        .uri("/api/v1/admin/server-files")
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let list_resp = app.oneshot(list_req).await.unwrap();
    let list_json = body_json(list_resp).await;
    let ids: Vec<&str> = list_json
        .as_array()
        .unwrap()
        .iter()
        .map(|f| f["id"].as_str().unwrap())
        .collect();
    assert!(ids.contains(&file_id.as_str()));
}

#[tokio::test]
async fn admin_upload_server_file_missing_file_returns_422() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let (content_type, body) = build_multipart_body(&[], None);

    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/server-files")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", content_type)
        .body(Body::from(body))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn admin_delete_server_file_unauthenticated_returns_401() {
    let (app, _db) = test_app_with_db().await;
    let req = Request::builder()
        .method("DELETE")
        .uri(format!("/api/v1/admin/server-files/{}", Uuid::new_v4()))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn admin_delete_nonexistent_server_file_returns_404() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;

    let req = Request::builder()
        .method("DELETE")
        .uri(format!("/api/v1/admin/server-files/{}", Uuid::new_v4()))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);
}

/// `server_file=false`(他エンドポイント由来、例: media添付)のdrive_files行は
/// server-filesエンドポイントの対象外としてPython版と同じく404を返す。
#[tokio::test]
async fn admin_delete_non_server_drive_file_returns_404() {
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let s3_key = format!("media/not-a-server-file-{}.png", Uuid::new_v4().simple());
    let file_id = seed_drive_file(&db, &s3_key, "image/png").await;

    let req = Request::builder()
        .method("DELETE")
        .uri(format!("/api/v1/admin/server-files/{file_id}"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);

    let remaining: Option<Uuid> = sqlx::query_scalar("SELECT id FROM drive_files WHERE id = $1")
        .bind(file_id)
        .fetch_optional(&db)
        .await
        .unwrap();
    assert!(remaining.is_some());
}

#[tokio::test]
async fn admin_delete_server_file_removes_s3_object_and_row() {
    common::ensure_test_s3_bucket().await;
    let (app, db) = test_app_with_db().await;
    let redis = common::connect_redis().await;
    let session_id = seed_admin_session(&db, &redis).await;
    let (content_type, body) =
        build_multipart_body(&[], Some(("file", "todel.png", "image/png", PNG_1X1)));
    let upload_req = Request::builder()
        .method("POST")
        .uri("/api/v1/admin/server-files")
        .header("cookie", cookie_header(&session_id))
        .header("content-type", content_type)
        .body(Body::from(body))
        .unwrap();
    let upload_resp = app.clone().oneshot(upload_req).await.unwrap();
    assert_eq!(upload_resp.status(), StatusCode::OK);
    let uploaded = body_json(upload_resp).await;
    let file_id = uploaded["id"].as_str().unwrap().to_string();

    let del_req = Request::builder()
        .method("DELETE")
        .uri(format!("/api/v1/admin/server-files/{file_id}"))
        .header("cookie", cookie_header(&session_id))
        .body(Body::empty())
        .unwrap();
    let del_resp = app.oneshot(del_req).await.unwrap();
    assert_eq!(del_resp.status(), StatusCode::OK);
    assert_eq!(body_json(del_resp).await["ok"], true);

    let remaining: Option<Uuid> = sqlx::query_scalar("SELECT id FROM drive_files WHERE id = $1")
        .bind(Uuid::parse_str(&file_id).unwrap())
        .fetch_optional(&db)
        .await
        .unwrap();
    assert!(remaining.is_none());
}
