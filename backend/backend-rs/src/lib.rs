pub mod activitypub;
pub mod auth;
pub mod config;
pub mod db;
pub mod delivery;
pub mod domain_block;
pub mod error;
pub mod follows;
pub mod hashtag;
pub mod hmac_sig;
pub mod http_signature;
pub mod mastodon_time;
pub mod note_response;
pub mod note_visibility;
pub mod notification;
pub mod remote_actor;
pub mod routes;
pub mod session;
pub mod shortcode;
pub mod ssrf;
pub mod state;
pub mod text_html;
pub mod totp;
pub mod valkey;

use axum::Router;
use state::AppState;

/// axum の `Router` を組み立てる。`main.rs` からはもちろん、
/// `tests/` の `tower::ServiceExt::oneshot` パターンからも同じ関数を使う
/// (Python 側の `httpx.ASGITransport(app=app)` と同じ役割)。
pub fn build_router(state: AppState) -> Router {
    Router::new()
        .merge(routes::accounts::router())
        .merge(routes::actor::router())
        .merge(routes::auth::router())
        .merge(routes::health::router())
        .merge(routes::webfinger::router())
        .merge(routes::nodeinfo::router())
        .merge(routes::media_proxy::router())
        .merge(routes::authorized_apps::router())
        .merge(routes::statuses::router())
        .with_state(state)
}
