pub mod config;
pub mod db;
pub mod error;
pub mod routes;
pub mod state;
pub mod valkey;

use axum::Router;
use state::AppState;

/// axum の `Router` を組み立てる。`main.rs` からはもちろん、
/// `tests/` の `tower::ServiceExt::oneshot` パターンからも同じ関数を使う
/// (Python 側の `httpx.ASGITransport(app=app)` と同じ役割)。
pub fn build_router(state: AppState) -> Router {
    // nodeinfo は Stage 1 の後続PRで追加する。
    Router::new()
        .merge(routes::health::router())
        .merge(routes::webfinger::router())
        .with_state(state)
}
