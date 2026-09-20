use std::net::SocketAddr;
use std::time::Duration;

use axum::body::{Body, Bytes};
use axum::extract::Path;
use axum::http::{header, Request, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use axum::Router;
use futures_util::stream;
use nekonoverse_backend_rs::{build_router, config::Config, db, hmac_sig, state::AppState, valkey};
use tower::ServiceExt;

const MAX_SIZE: usize = 20 * 1024 * 1024;

/// `allow_private_networks: true` で、SECRET_KEY/MEDIA_PROXY_KEY を固定した
/// テスト用アプリを組み立てる。`common::test_app_with_db` は
/// `Config::from_env()` を固定的に呼ぶため、SSRF 設定を上書きできる
/// ここだけの専用ヘルパーとして用意する。
async fn test_app(allow_private_networks: bool, total_timeout_secs: u64) -> (axum::Router, Config) {
    let mut config = Config::from_env();
    config.allow_private_networks = allow_private_networks;
    config.secret_key = "media-proxy-test-secret-key".to_string();
    config.media_proxy_key = String::new();
    config.media_proxy_total_timeout_secs = total_timeout_secs;

    let db_pool = db::connect(&config)
        .await
        .expect("failed to connect to test database");
    let redis_conn = valkey::connect(&config)
        .await
        .expect("failed to connect to test valkey");
    let state = AppState {
        db: db_pool,
        redis: redis_conn,
        config: config.clone(),
    };
    (build_router(state), config)
}

/// 署名済みの `/api/v1/media/proxy?url=...&h=...` パスを組み立てる。
fn signed_proxy_uri(config: &Config, target: &str, extra_params: &[(&str, &str)]) -> String {
    let h = hmac_sig::sign(config, target);
    let mut qs = url::form_urlencoded::Serializer::new(String::new());
    qs.append_pair("url", target);
    qs.append_pair("h", &h);
    for (k, v) in extra_params {
        qs.append_pair(k, v);
    }
    format!("/api/v1/media/proxy?{}", qs.finish())
}

async fn send_get(app: axum::Router, uri: &str) -> Response {
    app.oneshot(Request::builder().uri(uri).body(Body::empty()).unwrap())
        .await
        .unwrap()
}

const PNG_SIG: &[u8] = b"\x89PNG\r\n\x1a\n";

async fn png() -> impl IntoResponse {
    let mut body = PNG_SIG.to_vec();
    body.extend_from_slice(&[0u8; 32]);
    ([(header::CONTENT_TYPE, "image/png")], body)
}

async fn octet_png() -> impl IntoResponse {
    let mut body = PNG_SIG.to_vec();
    body.extend_from_slice(&[0u8; 16]);
    ([(header::CONTENT_TYPE, "application/octet-stream")], body)
}

async fn html_page() -> impl IntoResponse {
    (
        [(header::CONTENT_TYPE, "text/html")],
        "<html></html>".to_string(),
    )
}

async fn svg() -> impl IntoResponse {
    (
        [(header::CONTENT_TYPE, "image/svg+xml")],
        r#"<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>"#.to_string(),
    )
}

async fn redirect_relative() -> Response {
    (StatusCode::FOUND, [(header::LOCATION, "/png")]).into_response()
}

async fn redirect_loop() -> Response {
    (StatusCode::FOUND, [(header::LOCATION, "/redirect-loop")]).into_response()
}

async fn oversized_declared() -> impl IntoResponse {
    let body = vec![0u8; MAX_SIZE + 1];
    ([(header::CONTENT_TYPE, "image/png")], body)
}

async fn stream_nolen_big() -> impl IntoResponse {
    // Content-Length を送らせないため既知サイズの `Body::from` ではなく
    // ストリーミングボディを使う (合計 25MB > MAX_SIZE)。
    let chunks =
        stream::iter((0..25).map(|_| Ok::<_, std::io::Error>(Bytes::from(vec![0u8; 1_000_000]))));
    Response::builder()
        .status(StatusCode::OK)
        .header(header::CONTENT_TYPE, "image/png")
        .body(Body::from_stream(chunks))
        .unwrap()
}

async fn slow_trickle() -> impl IntoResponse {
    let chunks = stream::unfold((), |_| async move {
        tokio::time::sleep(Duration::from_millis(100)).await;
        Some((Ok::<_, std::io::Error>(Bytes::from_static(b"x")), ()))
    });
    Response::builder()
        .status(StatusCode::OK)
        .header(header::CONTENT_TYPE, "image/png")
        .body(Body::from_stream(chunks))
        .unwrap()
}

/// `avatar`/`emoji` 等の変換パラメータが送られてきたことを確認するためだけの
/// テスト用 media-proxy-rs スタブ。受け取った multipart の `file` フィールドを
/// そのまま `image/webp` として返す。
async fn transform_stub() -> impl IntoResponse {
    let mut body = PNG_SIG.to_vec();
    body.extend_from_slice(b"-transformed");
    ([(header::CONTENT_TYPE, "image/webp")], body)
}

async fn not_found_path(Path(_): Path<String>) -> StatusCode {
    StatusCode::NOT_FOUND
}

async fn spawn_mock_upstream() -> SocketAddr {
    let app = Router::new()
        .route("/png", get(png))
        .route("/octet-png", get(octet_png))
        .route("/html", get(html_page))
        .route("/svg", get(svg))
        .route("/redirect-relative", get(redirect_relative))
        .route("/redirect-loop", get(redirect_loop))
        .route("/oversized-declared", get(oversized_declared))
        .route("/stream-nolen-big", get(stream_nolen_big))
        .route("/slow", get(slow_trickle))
        .route("/transform", axum::routing::post(transform_stub))
        .route("/*rest", get(not_found_path));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    addr
}

#[tokio::test]
async fn missing_params_returns_422() {
    let (app, _config) = test_app(true, 30).await;
    let resp = send_get(app, "/api/v1/media/proxy").await;
    assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn invalid_signature_returns_403() {
    let (app, _config) = test_app(true, 30).await;
    let resp = send_get(
        app,
        "/api/v1/media/proxy?url=https://evil.example/img.png&h=0000000000000000",
    )
    .await;
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn invalid_url_scheme_returns_403() {
    let (app, config) = test_app(true, 30).await;
    let target = "ftp://example.com/file";
    let uri = signed_proxy_uri(&config, target, &[]);
    let resp = send_get(app, &uri).await;
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn blocks_private_host_by_default() {
    // allow_private_networks を明示的に false にした既定設定。
    let (app, config) = test_app(false, 30).await;
    let target = "http://127.0.0.1:1/nope";
    let uri = signed_proxy_uri(&config, target, &[]);
    let resp = send_get(app, &uri).await;
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn proxies_valid_image() {
    let addr = spawn_mock_upstream().await;
    let (app, config) = test_app(true, 30).await;
    let target = format!("http://{addr}/png");
    let uri = signed_proxy_uri(&config, &target, &[]);

    let resp = send_get(app, &uri).await;
    assert_eq!(resp.status(), StatusCode::OK);
    assert_eq!(
        resp.headers().get(header::CONTENT_TYPE).unwrap(),
        "image/png"
    );
    assert_eq!(
        resp.headers().get(header::CACHE_CONTROL).unwrap(),
        "public, max-age=86400"
    );
    assert_eq!(
        resp.headers().get(header::X_CONTENT_TYPE_OPTIONS).unwrap(),
        "nosniff"
    );
    let csp = resp
        .headers()
        .get(header::CONTENT_SECURITY_POLICY)
        .unwrap()
        .to_str()
        .unwrap();
    assert!(csp.contains("sandbox"));
    let body = http_body_util::BodyExt::collect(resp.into_body())
        .await
        .unwrap()
        .to_bytes();
    assert!(body.starts_with(PNG_SIG));
}

#[tokio::test]
async fn detects_image_type_from_magic_bytes_when_content_type_is_octet_stream() {
    let addr = spawn_mock_upstream().await;
    let (app, config) = test_app(true, 30).await;
    let target = format!("http://{addr}/octet-png");
    let uri = signed_proxy_uri(&config, &target, &[]);

    let resp = send_get(app, &uri).await;
    assert_eq!(resp.status(), StatusCode::OK);
    assert_eq!(
        resp.headers().get(header::CONTENT_TYPE).unwrap(),
        "image/png"
    );
}

#[tokio::test]
async fn rejects_disallowed_content_type() {
    let addr = spawn_mock_upstream().await;
    let (app, config) = test_app(true, 30).await;
    let target = format!("http://{addr}/html");
    let uri = signed_proxy_uri(&config, &target, &[]);

    let resp = send_get(app, &uri).await;
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn svg_is_served_sandboxed() {
    let addr = spawn_mock_upstream().await;
    let (app, config) = test_app(true, 30).await;
    let target = format!("http://{addr}/svg");
    let uri = signed_proxy_uri(&config, &target, &[]);

    let resp = send_get(app, &uri).await;
    assert_eq!(resp.status(), StatusCode::OK);
    let csp = resp
        .headers()
        .get(header::CONTENT_SECURITY_POLICY)
        .unwrap()
        .to_str()
        .unwrap();
    assert!(csp.contains("default-src 'none'"));
    assert!(!csp.contains("script-src"));
}

#[tokio::test]
async fn follows_relative_redirect() {
    let addr = spawn_mock_upstream().await;
    let (app, config) = test_app(true, 30).await;
    let target = format!("http://{addr}/redirect-relative");
    let uri = signed_proxy_uri(&config, &target, &[]);

    let resp = send_get(app, &uri).await;
    assert_eq!(resp.status(), StatusCode::OK);
    assert_eq!(
        resp.headers().get(header::CONTENT_TYPE).unwrap(),
        "image/png"
    );
}

#[tokio::test]
async fn too_many_redirects_returns_502() {
    let addr = spawn_mock_upstream().await;
    let (app, config) = test_app(true, 30).await;
    let target = format!("http://{addr}/redirect-loop");
    let uri = signed_proxy_uri(&config, &target, &[]);

    let resp = send_get(app, &uri).await;
    assert_eq!(resp.status(), StatusCode::BAD_GATEWAY);
}

#[tokio::test]
async fn rejects_oversized_declared_content_length() {
    let addr = spawn_mock_upstream().await;
    let (app, config) = test_app(true, 30).await;
    let target = format!("http://{addr}/oversized-declared");
    let uri = signed_proxy_uri(&config, &target, &[]);

    let resp = send_get(app, &uri).await;
    assert_eq!(resp.status(), StatusCode::PAYLOAD_TOO_LARGE);
}

#[tokio::test]
async fn stops_reading_when_stream_exceeds_limit_without_declared_length() {
    let addr = spawn_mock_upstream().await;
    let (app, config) = test_app(true, 30).await;
    let target = format!("http://{addr}/stream-nolen-big");
    let uri = signed_proxy_uri(&config, &target, &[]);

    let resp = send_get(app, &uri).await;
    assert_eq!(resp.status(), StatusCode::PAYLOAD_TOO_LARGE);
}

#[tokio::test]
async fn total_timeout_returns_504() {
    let addr = spawn_mock_upstream().await;
    // 全体タイムアウトを1秒に短縮してテストを高速化する
    // (本番デフォルトの30秒を待つと遅すぎるため)。
    let (app, config) = test_app(true, 1).await;
    let target = format!("http://{addr}/slow");
    let uri = signed_proxy_uri(&config, &target, &[]);

    let resp = send_get(app, &uri).await;
    assert_eq!(resp.status(), StatusCode::GATEWAY_TIMEOUT);
}

#[tokio::test]
async fn transform_params_call_media_proxy_rs_and_return_webp() {
    let addr = spawn_mock_upstream().await;
    let (_, mut config) = test_app(true, 30).await;
    config.media_proxy_transform_url = Some(format!("http://{addr}"));
    // transform_url を差し替えたので state ごと作り直す。
    let db_pool = db::connect(&config).await.unwrap();
    let redis_conn = valkey::connect(&config).await.unwrap();
    let app = build_router(AppState {
        db: db_pool,
        redis: redis_conn,
        config: config.clone(),
    });

    let target = format!("http://{addr}/png");
    let uri = signed_proxy_uri(&config, &target, &[("avatar", "1")]);

    let resp = send_get(app, &uri).await;
    assert_eq!(resp.status(), StatusCode::OK);
    assert_eq!(
        resp.headers().get(header::CONTENT_TYPE).unwrap(),
        "image/webp"
    );
    let body = http_body_util::BodyExt::collect(resp.into_body())
        .await
        .unwrap()
        .to_bytes();
    assert!(body.ends_with(b"-transformed"));
}
