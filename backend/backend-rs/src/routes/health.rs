use axum::routing::get;
use axum::{Json, Router};
use serde_json::{json, Value};

use crate::state::AppState;

/// `GET /api/v1/health` を移植したもの (`backend/app/main.py`)。
/// DB/Valkeyへの依存は一切ない完全に静的な応答。
async fn health() -> Json<Value> {
    Json(json!({ "status": "ok" }))
}

pub fn router() -> Router<AppState> {
    Router::new().route("/api/v1/health", get(health))
}
