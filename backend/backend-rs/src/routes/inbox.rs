//! `app/activitypub/routes.py` の `user_inbox`/`shared_inbox` エンドポイント配線
//! (H-5: レート制限、H-4: ボディサイズ上限、Digest/HTTP Signature検証、鍵所有者と
//! `activity.actor`の一致検証)を移植したもの。ハンドラーディスパッチ本体
//! (`process_inbox_activity`とその先の各activity種別ハンドラー)は`inbox.rs`
//! 側に委譲する。
//!
//! クライアントIP解決は`routes/auth.rs`と同じ理由でnginxが付与する
//! `X-Real-IP`ヘッダーを読む(Python版の`request.client.host`は実運用では
//! 機能していない値、詳細は`routes/auth.rs`冒頭のコメント参照)。

use std::collections::HashMap;

use axum::body::to_bytes;
use axum::extract::{Path, Request, State};
use axum::http::{HeaderMap, Method, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::post;
use axum::Router;
use serde_json::Value;
use uuid::Uuid;

use crate::error::AppError;
use crate::http_signature::{parse_signature_header, verify_digest, verify_signature};
use crate::inbox::process_inbox_activity;
use crate::remote_actor::get_actor_public_key;
use crate::state::AppState;

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/users/:username/inbox", post(user_inbox))
        .route("/inbox", post(shared_inbox))
}

/// H-4: Inboxリクエストのボディサイズ上限 (1MB)。
const MAX_INBOX_BODY_SIZE: usize = 1024 * 1024;

/// H-5: Inboxレート制限。
const INBOX_MAX_REQUESTS: i64 = 200;
const INBOX_RATE_TTL: i64 = 60;

/// `app.activitypub.routes._check_inbox_rate_limit` を移植したもの。
async fn check_inbox_rate_limit(state: &AppState, client_ip: &str) -> Result<(), AppError> {
    use redis::AsyncCommands;
    let key = format!("inbox_rate:{client_ip}");
    let mut redis = state.redis.clone();
    // Python版の`try/except Exception: pass`と同じく、Valkey障害はinboxの疎通
    // 自体を落とさないよう無視する(レート制限はベストエフォート)。
    let attempts: Option<i64> = redis.get(&key).await.unwrap_or(None);
    if attempts.is_some_and(|a| a >= INBOX_MAX_REQUESTS) {
        return Err(AppError::new(
            StatusCode::TOO_MANY_REQUESTS,
            "Too many requests",
        ));
    }
    let _: Result<i64, _> = redis.incr(&key, 1).await;
    let _: Result<(), _> = redis.expire(&key, INBOX_RATE_TTL).await;
    Ok(())
}

/// `app.activitypub.routes._read_inbox_body` を移植したもの。`axum::body::to_bytes`
/// の`limit`引数がPython版の「読みながら上限を確認する」ストリーミング上限
/// チェックと同じ役割を果たす。
async fn read_inbox_body(
    headers: &HeaderMap,
    body: axum::body::Body,
) -> Result<axum::body::Bytes, AppError> {
    if let Some(cl) = headers.get(axum::http::header::CONTENT_LENGTH) {
        let s = cl
            .to_str()
            .map_err(|_| AppError::bad_request("Invalid Content-Length"))?;
        if !s.chars().all(|c| c.is_ascii_digit()) {
            return Err(AppError::bad_request("Invalid Content-Length"));
        }
        let n: usize = s
            .parse()
            .map_err(|_| AppError::bad_request("Invalid Content-Length"))?;
        if n > MAX_INBOX_BODY_SIZE {
            return Err(AppError::new(
                StatusCode::PAYLOAD_TOO_LARGE,
                "Request body too large",
            ));
        }
    }

    to_bytes(body, MAX_INBOX_BODY_SIZE)
        .await
        .map_err(|_| AppError::new(StatusCode::PAYLOAD_TOO_LARGE, "Request body too large"))
}

/// `app.activitypub.routes.verify_inbox_signature` + `_verify_digest` +
/// JSON-LD配列展開 + `_verify_key_actor_match` を移植したもの。検証済みの
/// activityを返す。
async fn verify_and_parse_activity(
    state: &AppState,
    headers: &HeaderMap,
    method: &Method,
    path: &str,
    body: &[u8],
) -> Result<Value, AppError> {
    let digest_header = headers.get("digest").and_then(|v| v.to_str().ok());
    if !verify_digest(body, digest_header) {
        tracing::warn!("Invalid or missing Digest header");
        return Err(AppError::bad_request("Invalid Digest header"));
    }

    let sig_header = headers.get("signature").and_then(|v| v.to_str().ok());
    let Some(sig_header) = sig_header else {
        tracing::warn!("Invalid HTTP Signature: missing Signature header");
        return Err(AppError::new(StatusCode::UNAUTHORIZED, "Invalid signature"));
    };
    let params = parse_signature_header(sig_header);
    let key_id = params.get("keyId").cloned().unwrap_or_default();
    if key_id.is_empty() {
        tracing::warn!("Invalid HTTP Signature: missing keyId");
        return Err(AppError::new(StatusCode::UNAUTHORIZED, "Invalid signature"));
    }

    let key_info = get_actor_public_key(state, &key_id).await?;
    let Some(key_info) = key_info else {
        tracing::warn!(key_id, "Invalid HTTP Signature from unresolvable key_id");
        return Err(AppError::new(StatusCode::UNAUTHORIZED, "Invalid signature"));
    };

    let headers_map: HashMap<String, String> = headers
        .iter()
        .filter_map(|(k, v)| {
            v.to_str()
                .ok()
                .map(|v| (k.as_str().to_lowercase(), v.to_string()))
        })
        .collect();

    let valid = verify_signature(
        &key_info.public_key_material,
        sig_header,
        method.as_str(),
        path,
        &headers_map,
        Some(key_info.algorithm.as_str()),
    );
    if !valid {
        tracing::warn!(key_id, "Invalid HTTP Signature");
        return Err(AppError::new(StatusCode::UNAUTHORIZED, "Invalid signature"));
    }

    let mut activity: Value =
        serde_json::from_slice(body).map_err(|_| AppError::bad_request("Invalid JSON"))?;
    if let Value::Array(arr) = activity {
        activity = arr
            .into_iter()
            .next()
            .ok_or_else(|| AppError::bad_request("Empty activity array"))?;
    }

    // 署名鍵のアクターとactivityのactorが一致するか検証
    let activity_actor = activity.get("actor").and_then(Value::as_str).unwrap_or("");
    if activity_actor.is_empty() {
        return Err(AppError::new(
            StatusCode::UNAUTHORIZED,
            "Missing actor or key_id",
        ));
    }
    let key_actor = key_id.split('#').next().unwrap_or("");
    if key_actor != activity_actor {
        tracing::warn!(key_actor, activity_actor, "Key actor mismatch");
        return Err(AppError::new(
            StatusCode::UNAUTHORIZED,
            "Key owner does not match activity actor",
        ));
    }

    Ok(activity)
}

fn client_ip(headers: &HeaderMap) -> String {
    headers
        .get("x-real-ip")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("unknown")
        .to_string()
}

fn request_path_and_query(req: &Request) -> String {
    let uri = req.uri();
    match uri.query() {
        Some(q) => format!("{}?{q}", uri.path()),
        None => uri.path().to_string(),
    }
}

async fn dispatch_inbox(state: AppState, req: Request) -> Result<Response, AppError> {
    let client_ip = client_ip(req.headers());
    check_inbox_rate_limit(&state, &client_ip).await?;

    let method = req.method().clone();
    let path = request_path_and_query(&req);
    let headers = req.headers().clone();
    let body = read_inbox_body(&headers, req.into_body()).await?;

    let activity = verify_and_parse_activity(&state, &headers, &method, &path, &body).await?;

    process_inbox_activity(&state, &activity).await?;
    Ok(StatusCode::ACCEPTED.into_response())
}

async fn user_inbox(
    State(state): State<AppState>,
    Path(username): Path<String>,
    req: Request,
) -> Result<Response, AppError> {
    let exists: Option<Uuid> =
        sqlx::query_scalar("SELECT id FROM actors WHERE username = $1 AND domain IS NULL")
            .bind(username.to_lowercase())
            .fetch_optional(&state.db)
            .await?;
    if exists.is_none() {
        return Err(AppError::not_found("Actor not found"));
    }

    dispatch_inbox(state, req).await
}

async fn shared_inbox(State(state): State<AppState>, req: Request) -> Result<Response, AppError> {
    dispatch_inbox(state, req).await
}
