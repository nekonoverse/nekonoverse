use axum::body::Body;
use axum::http::{Request, StatusCode};
use tower::ServiceExt;

mod common;

/// `backend/tests/` (Python) に対応する health check テストは
/// `main.py` 全体を対象にしたテストの一部としてしか存在しなかったため
/// (単独ファイルなし)、削除対象の Python テストファイルはない。
#[tokio::test]
async fn health_returns_ok() {
    let app = common::test_app().await;
    let response = app
        .oneshot(
            Request::builder()
                .uri("/api/v1/health")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);

    let body = http_body_util::BodyExt::collect(response.into_body())
        .await
        .unwrap()
        .to_bytes();
    let json: serde_json::Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(json, serde_json::json!({ "status": "ok" }));
}
