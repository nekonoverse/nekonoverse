pub mod activitypub;
pub mod auth;
pub mod config;
pub mod db;
pub mod delivery;
pub mod domain_block;
pub mod error;
pub mod follows;
pub mod hmac_sig;
pub mod note_visibility;
pub mod routes;
pub mod ssrf;
pub mod state;
pub mod valkey;

use axum::Router;
use state::AppState;

/// axum の `Router` を組み立てる。`main.rs` からはもちろん、
/// `tests/` の `tower::ServiceExt::oneshot` パターンからも同じ関数を使う
/// (Python 側の `httpx.ASGITransport(app=app)` と同じ役割)。
pub fn build_router(state: AppState) -> Router {
    Router::new()
        .merge(routes::health::router())
        .merge(routes::webfinger::router())
        .merge(routes::nodeinfo::router())
        .merge(routes::media_proxy::router())
        .merge(routes::authorized_apps::router())
        .merge(routes::statuses::router())
        .with_state(state)
}
