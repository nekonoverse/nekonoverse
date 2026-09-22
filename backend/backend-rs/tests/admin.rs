//! `routes/admin.rs`(domain_blocks系)と`admin_auth::require_permission`の
//! 結合テスト。`app/dependencies.get_permitted_staff("domains")`と同じ権限
//! 判定(admin role即許可・非staffは拒否・カスタムroleはpermissions JSONB次第)
//! およびOAuthトークン経由での`admin:read`/`admin:write`スコープ要求
//! (`_require_admin_scope`)を検証する。

use axum::body::Body;
use axum::http::{Request, StatusCode};
use serde_json::{json, Value};
use sqlx::PgPool;
use tower::ServiceExt;
use uuid::Uuid;

mod common;
use common::{
    seed_local_actor, seed_oauth_application, seed_oauth_token, seed_session, seed_user,
    test_app_with_db,
};

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
