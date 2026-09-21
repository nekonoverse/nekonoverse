use axum::body::Body;
use axum::http::{header, Request, StatusCode};
use serde_json::Value;
use tower::ServiceExt;
use uuid::Uuid;

mod common;
use common::seed_local_actor;

const AP_ACCEPT: &str = "application/activity+json";

async fn get(
    app: axum::Router,
    uri: &str,
    accept: Option<&str>,
) -> (StatusCode, axum::http::HeaderMap, Value, String) {
    let mut builder = Request::builder().method("GET").uri(uri);
    if let Some(accept) = accept {
        builder = builder.header(header::ACCEPT, accept);
    }
    let response = app
        .oneshot(builder.body(Body::empty()).unwrap())
        .await
        .unwrap();
    let status = response.status();
    let headers = response.headers().clone();
    let body = http_body_util::BodyExt::collect(response.into_body())
        .await
        .unwrap()
        .to_bytes();
    let raw = String::from_utf8_lossy(&body).to_string();
    let json: Value = if body.is_empty() {
        Value::Null
    } else {
        serde_json::from_slice(&body).unwrap_or(Value::Null)
    };
    (status, headers, json, raw)
}

#[tokio::test]
async fn get_actor_local_public_actor_returns_ap_json() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("actortest1{}", Uuid::new_v4().simple());
    seed_local_actor(&db, &username).await;

    let (status, headers, json, _raw) =
        get(app, &format!("/users/{username}"), Some(AP_ACCEPT)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        headers.get(header::CONTENT_TYPE).unwrap(),
        "application/activity+json; charset=utf-8"
    );
    assert_eq!(json["type"], "Person");
    assert_eq!(json["preferredUsername"], username);
    assert_eq!(json["id"], format!("https://localhost/users/{username}"));
    assert_eq!(
        json["inbox"],
        format!("https://localhost/users/{username}/inbox")
    );
    assert_eq!(
        json["followers"],
        format!("https://localhost/users/{username}/followers")
    );
    assert_eq!(
        json["featured"],
        format!("https://localhost/users/{username}/featured")
    );
    assert_eq!(json["publicKey"]["publicKeyPem"], "dummy-pem");
    assert!(json.get("assertionMethod").is_none());
    assert!(json.get("summary").is_none());
    assert!(json.get("attachment").is_none());
}

#[tokio::test]
async fn get_actor_without_ap_accept_redirects_to_profile() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("actortest2{}", Uuid::new_v4().simple());
    seed_local_actor(&db, &username).await;

    let (status, headers, _json, _raw) = get(app, &format!("/users/{username}"), None).await;
    assert_eq!(status, StatusCode::FOUND);
    assert_eq!(
        headers.get(header::LOCATION).unwrap(),
        &format!("/@{username}")
    );
}

#[tokio::test]
async fn get_actor_not_found_returns_404() {
    let (app, _db) = common::test_app_with_db().await;
    let (status, _headers, json, _raw) = get(
        app,
        &format!("/users/nonexistent-{}", Uuid::new_v4().simple()),
        Some(AP_ACCEPT),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(json["detail"], "Actor not found");
}

#[tokio::test]
async fn get_actor_deleted_returns_tombstone_for_ap_request() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("actortest4{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    sqlx::query("UPDATE actors SET deleted_at = now() WHERE id = $1")
        .bind(actor_id)
        .execute(&db)
        .await
        .unwrap();

    let (status, headers, json, _raw) =
        get(app, &format!("/users/{username}"), Some(AP_ACCEPT)).await;
    assert_eq!(status, StatusCode::GONE);
    assert_eq!(
        headers.get(header::CONTENT_TYPE).unwrap(),
        "application/activity+json; charset=utf-8"
    );
    assert_eq!(json["type"], "Tombstone");
    assert_eq!(json["@context"], "https://www.w3.org/ns/activitystreams");
}

#[tokio::test]
async fn get_actor_deleted_returns_plain_410_for_html_request() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("actortest5{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    sqlx::query("UPDATE actors SET deleted_at = now() WHERE id = $1")
        .bind(actor_id)
        .execute(&db)
        .await
        .unwrap();

    let (status, _headers, json, _raw) = get(app, &format!("/users/{username}"), None).await;
    assert_eq!(status, StatusCode::GONE);
    assert_eq!(json["detail"], "Gone");
}

#[tokio::test]
async fn get_actor_suspended_returns_410() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("actortest6{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    sqlx::query("UPDATE actors SET suspended_at = now() WHERE id = $1")
        .bind(actor_id)
        .execute(&db)
        .await
        .unwrap();

    let (status, _headers, json, _raw) =
        get(app, &format!("/users/{username}"), Some(AP_ACCEPT)).await;
    assert_eq!(status, StatusCode::GONE);
    assert_eq!(json["detail"], "Gone");
}

#[tokio::test]
async fn get_actor_includes_ed25519_assertion_method_when_present() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("actortest7{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    sqlx::query("UPDATE actors SET public_key_ed25519_multibase = $1 WHERE id = $2")
        .bind("z6MkTestMultibaseKey")
        .bind(actor_id)
        .execute(&db)
        .await
        .unwrap();

    let (status, _headers, json, _raw) =
        get(app, &format!("/users/{username}"), Some(AP_ACCEPT)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        json["assertionMethod"][0]["publicKeyMultibase"],
        "z6MkTestMultibaseKey"
    );
    assert_eq!(json["assertionMethod"][0]["type"], "Multikey");
}

#[tokio::test]
async fn get_actor_includes_fields_as_attachment() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("actortest8{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    sqlx::query("UPDATE actors SET fields = $1::jsonb WHERE id = $2")
        .bind(r#"[{"name": "Website", "value": "https://example.com"}]"#)
        .bind(actor_id)
        .execute(&db)
        .await
        .unwrap();

    let (status, _headers, json, _raw) =
        get(app, &format!("/users/{username}"), Some(AP_ACCEPT)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["attachment"][0]["type"], "PropertyValue");
    assert_eq!(json["attachment"][0]["name"], "Website");
    assert_eq!(json["attachment"][0]["value"], "https://example.com");
}
