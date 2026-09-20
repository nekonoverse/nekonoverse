use axum::body::Body;
use axum::http::{Request, StatusCode};
use serde_json::Value;
use tower::ServiceExt;
use uuid::Uuid;

mod common;
use common::seed_local_actor;

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
    let json: Value = if body.is_empty() {
        Value::Null
    } else {
        serde_json::from_slice(&body).unwrap_or(Value::Null)
    };
    (status, json)
}

#[tokio::test]
async fn webfinger_success() {
    let (app, db) = common::test_app_with_db().await;
    // テストDBは全テスト関数(並列実行される)で共有され、`(username, domain)`
    // にUNIQUE制約があるため、再実行時の衝突を避けるためユーザー名は都度ユニークにする。
    let username = format!("testuser{}", Uuid::new_v4().simple());
    seed_local_actor(&db, &username).await;

    let (status, json) = get(
        app,
        &format!("/.well-known/webfinger?resource=acct:{username}@localhost"),
    )
    .await;

    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["subject"], format!("acct:{username}@localhost"));
    let aliases = json["aliases"].as_array().unwrap();
    assert_eq!(aliases.len(), 2);
    assert!(aliases
        .iter()
        .any(|a| a.as_str().unwrap().contains(&username)));
    let links = json["links"].as_array().unwrap();
    let self_link = links.iter().find(|l| l["rel"] == "self").unwrap();
    assert_eq!(self_link["type"], "application/activity+json");
}

#[tokio::test]
async fn webfinger_invalid_resource_format() {
    let (app, _db) = common::test_app_with_db().await;
    let (status, json) = get(app, "/.well-known/webfinger?resource=invalid:something").await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert!(json["detail"]
        .as_str()
        .unwrap()
        .contains("Invalid resource format"));
}

#[tokio::test]
async fn webfinger_invalid_acct_format() {
    let (app, _db) = common::test_app_with_db().await;
    let (status, json) = get(app, "/.well-known/webfinger?resource=acct:nodomainnobody").await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert!(json["detail"]
        .as_str()
        .unwrap()
        .contains("Invalid acct format"));
}

#[tokio::test]
async fn webfinger_wrong_domain() {
    let (app, _db) = common::test_app_with_db().await;
    let (status, _json) = get(
        app,
        "/.well-known/webfinger?resource=acct:user@wrong.example",
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn webfinger_user_not_found() {
    let (app, _db) = common::test_app_with_db().await;
    let (status, _json) = get(
        app,
        "/.well-known/webfinger?resource=acct:nonexistent@localhost",
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn webfinger_missing_resource() {
    let (app, _db) = common::test_app_with_db().await;
    let (status, _json) = get(app, "/.well-known/webfinger").await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
}
