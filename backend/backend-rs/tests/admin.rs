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
use serde_json::{json, Value};
use sqlx::PgPool;
use tower::ServiceExt;
use uuid::Uuid;

mod common;
use common::{
    seed_follow, seed_local_actor, seed_note_with_visibility, seed_oauth_application,
    seed_oauth_token, seed_remote_actor, seed_report, seed_session, seed_user, test_app_with_db,
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
