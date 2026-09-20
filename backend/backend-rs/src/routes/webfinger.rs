use axum::extract::{Query, State};
use axum::http::{header, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use axum::Router;
use serde::{Deserialize, Serialize};

use crate::error::AppError;
use crate::state::AppState;

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/.well-known/host-meta", get(host_meta))
        .route("/.well-known/webfinger", get(webfinger))
}

/// `activitypub/webfinger.py` の `host_meta` を移植したもの。
/// LRDD ディスカバリ用の XRD host-meta (Pleroma/GNU Social で使用)。
async fn host_meta(State(state): State<AppState>) -> Response {
    let server_url = state.config.server_url();
    let xml = format!(
        r#"<?xml version="1.0" encoding="UTF-8"?><XRD xmlns="http://docs.oasis-open.org/ns/xri/xrd-1.0"><Link rel="lrdd" template="{server_url}/.well-known/webfinger?resource={{uri}}" /></XRD>"#
    );
    (
        StatusCode::OK,
        [(header::CONTENT_TYPE, "application/xrd+xml")],
        xml,
    )
        .into_response()
}

/// `resource` は axum の `Query` 抽出が失敗しないよう `Option` にし、欠落時は
/// ハンドラ内で FastAPI と同じ 422 を明示的に返す (axum のデフォルト拒否は 400 になるため)。
#[derive(Deserialize)]
struct WebfingerQuery {
    resource: Option<String>,
}

#[derive(Serialize)]
struct WebfingerLink {
    rel: &'static str,
    #[serde(rename = "type")]
    type_: &'static str,
    href: String,
}

#[derive(Serialize)]
struct WebfingerResponse {
    subject: String,
    aliases: Vec<String>,
    links: Vec<WebfingerLink>,
}

#[derive(sqlx::FromRow)]
struct ActorUsername {
    username: String,
}

/// `activitypub/webfinger.py` の `webfinger` を移植したもの。
async fn webfinger(
    State(state): State<AppState>,
    Query(params): Query<WebfingerQuery>,
) -> Result<Response, AppError> {
    let resource = params
        .resource
        .ok_or_else(|| AppError::new(StatusCode::UNPROCESSABLE_ENTITY, "Field required"))?;

    let Some(acct) = resource.strip_prefix("acct:") else {
        return Err(AppError::bad_request("Invalid resource format"));
    };

    let Some((username, domain)) = acct.split_once('@') else {
        return Err(AppError::bad_request("Invalid acct format"));
    };

    if domain != state.config.domain.as_str() {
        return Err(AppError::not_found("User not found"));
    }

    // `get_actor_by_username(db, username, domain=None)` と同一クエリ:
    // ローカルアクターは username が小文字で格納されている前提で完全一致検索する。
    let actor = sqlx::query_as::<_, ActorUsername>(
        "SELECT username FROM actors WHERE username = $1 AND domain IS NULL",
    )
    .bind(username.to_lowercase())
    .fetch_optional(&state.db)
    .await?
    .ok_or_else(|| AppError::not_found("User not found"))?;

    let server_url = state.config.server_url();
    let actor_url = format!("{server_url}/users/{}", actor.username);
    let profile_url = format!("{server_url}/@{}", actor.username);

    let body = WebfingerResponse {
        subject: resource,
        aliases: vec![actor_url.clone(), profile_url.clone()],
        links: vec![
            WebfingerLink {
                rel: "self",
                type_: "application/activity+json",
                href: actor_url,
            },
            WebfingerLink {
                rel: "http://webfinger.net/rel/profile-page",
                type_: "text/html",
                href: profile_url,
            },
        ],
    };

    let json = serde_json::to_string(&body).map_err(|e| {
        tracing::error!(error = %e, "failed to serialize webfinger response");
        AppError::new(StatusCode::INTERNAL_SERVER_ERROR, "Internal server error")
    })?;

    Ok((
        StatusCode::OK,
        [(header::CONTENT_TYPE, "application/jrd+json")],
        json,
    )
        .into_response())
}
