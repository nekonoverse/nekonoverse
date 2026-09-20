use axum::body::Body;
use axum::http::{Request, StatusCode};
use chrono::Utc;
use serde_json::Value;
use sqlx::PgPool;
use std::sync::LazyLock;
use tokio::sync::Mutex;
use tower::ServiceExt;
use uuid::Uuid;

mod common;
use common::{seed_local_actor, seed_note};

/// `registration_mode`/`server_name` 等は `server_settings` の固定キーで
/// テストDB全体を通じてグローバルに共有される (Python側は `db` フィクスチャの
/// トランザクションROLLBACKで分離しているが、こちらはコミット直書きのため
/// 分離できない)。これらを読み書きするテストは並列実行させず直列化する。
static SETTINGS_LOCK: LazyLock<Mutex<()>> = LazyLock::new(|| Mutex::new(()));

async fn set_setting(db: &PgPool, key: &str, value: &str) {
    sqlx::query(
        r#"
        INSERT INTO server_settings (key, value, updated_at) VALUES ($1, $2, now())
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
        "#,
    )
    .bind(key)
    .bind(value)
    .execute(db)
    .await
    .expect("failed to upsert test setting");
}

async fn clear_setting_cache(redis: &mut redis::aio::ConnectionManager, key: &str) {
    let _: () = redis::AsyncCommands::del(redis, format!("setting:{key}"))
        .await
        .expect("failed to clear setting cache");
}

async fn get(app: axum::Router, uri: &str) -> (StatusCode, Value) {
    let response = app
        .oneshot(Request::builder().uri(uri).body(Body::empty()).unwrap())
        .await
        .unwrap();
    let status = response.status();
    let body = http_body_util::BodyExt::collect(response.into_body())
        .await
        .unwrap()
        .to_bytes();
    let json: Value = serde_json::from_slice(&body).unwrap_or(Value::Null);
    (status, json)
}

#[tokio::test]
async fn nodeinfo_discovery() {
    let (app, _db) = common::test_app_with_db().await;
    let (status, json) = get(app, "/.well-known/nodeinfo").await;
    assert_eq!(status, StatusCode::OK);
    let links = json["links"].as_array().unwrap();
    assert_eq!(links.len(), 1);
    assert_eq!(
        links[0]["rel"],
        "http://nodeinfo.diaspora.software/ns/schema/2.0"
    );
    assert!(links[0]["href"]
        .as_str()
        .unwrap()
        .ends_with("/nodeinfo/2.0"));
}

#[tokio::test]
async fn nodeinfo_shape() {
    let (app, _db) = common::test_app_with_db().await;
    let (status, json) = get(app, "/nodeinfo/2.0").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["version"], "2.0");
    assert_eq!(json["software"]["name"], "nekonoverse");
    assert_eq!(json["protocols"], serde_json::json!(["activitypub"]));
    assert!(json["usage"]["users"].is_object());
    assert!(json["usage"]["localPosts"].is_number());
}

#[tokio::test]
async fn nodeinfo_user_count() {
    let (app, db) = common::test_app_with_db().await;
    seed_local_actor(&db, &format!("nitest{}", Uuid::new_v4().simple())).await;
    let (_status, json) = get(app, "/nodeinfo/2.0").await;
    assert!(json["usage"]["users"]["total"].as_i64().unwrap() >= 1);
}

#[tokio::test]
async fn nodeinfo_active_users_and_post_count() {
    let (app, db) = common::test_app_with_db().await;
    let actor_id = seed_local_actor(&db, &format!("nitest{}", Uuid::new_v4().simple())).await;
    seed_note(&db, actor_id, Utc::now()).await;

    let (_status, json) = get(app, "/nodeinfo/2.0").await;
    assert!(json["usage"]["users"]["activeHalfyear"].as_i64().unwrap() >= 1);
    assert!(json["usage"]["users"]["activeMonth"].as_i64().unwrap() >= 1);
    assert!(json["usage"]["localPosts"].as_i64().unwrap() >= 1);
}

#[tokio::test]
async fn nodeinfo_open_registrations_is_bool() {
    let (app, _db) = common::test_app_with_db().await;
    let (_status, json) = get(app, "/nodeinfo/2.0").await;
    assert!(json["openRegistrations"].is_boolean());
}

#[tokio::test]
async fn nodeinfo_registration_modes() {
    let _guard = SETTINGS_LOCK.lock().await;
    let (_app0, db) = common::test_app_with_db().await;

    for (mode, expected) in [
        ("invite", false),
        ("approval", true),
        ("open", true),
        ("closed", false),
    ] {
        set_setting(&db, "registration_mode", mode).await;
        let (app, _) = common::test_app_with_db().await;
        let mut redis = nekonoverse_backend_rs::valkey::connect(
            &nekonoverse_backend_rs::config::Config::from_env(),
        )
        .await
        .unwrap();
        clear_setting_cache(&mut redis, "registration_mode").await;

        let (_status, json) = get(app, "/nodeinfo/2.0").await;
        assert_eq!(json["openRegistrations"], expected, "mode={mode}");
    }
}

#[tokio::test]
async fn nodeinfo_registration_open_legacy() {
    let _guard = SETTINGS_LOCK.lock().await;
    let (_app0, db) = common::test_app_with_db().await;

    // registration_mode が未設定であることを保証してからレガシーキーを検証する。
    sqlx::query("DELETE FROM server_settings WHERE key = 'registration_mode'")
        .execute(&db)
        .await
        .unwrap();
    set_setting(&db, "registration_open", "true").await;

    let (app, _) = common::test_app_with_db().await;
    let mut redis = nekonoverse_backend_rs::valkey::connect(
        &nekonoverse_backend_rs::config::Config::from_env(),
    )
    .await
    .unwrap();
    clear_setting_cache(&mut redis, "registration_mode").await;
    clear_setting_cache(&mut redis, "registration_open").await;

    let (_status, json) = get(app, "/nodeinfo/2.0").await;
    assert_eq!(json["openRegistrations"], true);
}

#[tokio::test]
async fn nodeinfo_metadata_defaults() {
    // server_name 等がデフォルト (未設定) であることに依存するため、
    // 他の設定変更テストと同じロックで直列化する。
    let _guard = SETTINGS_LOCK.lock().await;
    let (app, _db) = common::test_app_with_db().await;
    let (_status, json) = get(app, "/nodeinfo/2.0").await;
    assert_eq!(json["metadata"]["nodeName"], "Nekonoverse");
    let features = json["metadata"]["features"].as_array().unwrap();
    assert!(features.iter().any(|f| f == "emoji_reactions"));
}

#[tokio::test]
async fn nodeinfo_custom_server_name_and_metadata() {
    let _guard = SETTINGS_LOCK.lock().await;
    let (_app0, db) = common::test_app_with_db().await;

    set_setting(&db, "server_name", "My Custom Server").await;
    set_setting(&db, "server_description", "Custom description").await;
    set_setting(&db, "server_icon_url", "https://example.com/icon.png").await;
    set_setting(&db, "server_theme_color", "#ff6600").await;

    let (app, _) = common::test_app_with_db().await;
    let mut redis = nekonoverse_backend_rs::valkey::connect(
        &nekonoverse_backend_rs::config::Config::from_env(),
    )
    .await
    .unwrap();
    for key in [
        "server_name",
        "server_description",
        "server_icon_url",
        "server_theme_color",
    ] {
        clear_setting_cache(&mut redis, key).await;
    }

    let (_status, json) = get(app, "/nodeinfo/2.0").await;
    assert_eq!(json["metadata"]["nodeName"], "My Custom Server");
    assert_eq!(json["metadata"]["nodeDescription"], "Custom description");
    assert_eq!(json["metadata"]["iconUrl"], "https://example.com/icon.png");
    assert_eq!(json["metadata"]["themeColor"], "#ff6600");

    // 後続テストへの影響を避けるため元に戻す。
    sqlx::query(
        "DELETE FROM server_settings WHERE key IN ('server_name','server_description','server_icon_url','server_theme_color')",
    )
    .execute(&db)
    .await
    .unwrap();
    for key in [
        "server_name",
        "server_description",
        "server_icon_url",
        "server_theme_color",
    ] {
        clear_setting_cache(&mut redis, key).await;
    }
}
