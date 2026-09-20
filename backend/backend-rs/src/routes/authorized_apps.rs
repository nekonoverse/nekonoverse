use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::{delete, get};
use axum::{Json, Router};
use chrono::{DateTime, Utc};
use serde::Serialize;
use serde_json::json;
use uuid::Uuid;

use crate::auth::CurrentUser;
use crate::error::AppError;
use crate::state::AppState;

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/api/v1/authorized_apps", get(list_authorized_apps))
        .route(
            "/api/v1/authorized_apps/:app_id",
            delete(revoke_authorized_app),
        )
}

/// `app/api/mastodon/statuses.py` の `_to_mastodon_datetime` と同一。
fn to_mastodon_datetime(dt: DateTime<Utc>) -> String {
    format!(
        "{}.{:03}Z",
        dt.format("%Y-%m-%dT%H:%M:%S"),
        dt.timestamp_subsec_millis()
    )
}

#[derive(sqlx::FromRow)]
struct AuthorizedAppRow {
    id: Uuid,
    name: String,
    website: Option<String>,
    scopes: String,
    first_authorized_at: DateTime<Utc>,
}

#[derive(Serialize)]
struct AuthorizedAppResponse {
    id: String,
    name: String,
    website: Option<String>,
    scopes: Vec<String>,
    created_at: String,
}

/// `app/api/authorized_apps.py` の `list_authorized_apps` を移植したもの。
async fn list_authorized_apps(
    State(state): State<AppState>,
    current_user: CurrentUser,
) -> Result<Response, AppError> {
    let now = Utc::now();
    let rows: Vec<AuthorizedAppRow> = sqlx::query_as(
        r#"
        SELECT app.id, app.name, app.website, app.scopes,
               MIN(token.created_at) AS first_authorized_at
        FROM oauth_applications app
        JOIN oauth_tokens token ON token.application_id = app.id
        WHERE token.user_id = $1
          AND token.revoked_at IS NULL
          AND (token.expires_at IS NULL OR token.expires_at > $2)
        GROUP BY app.id
        ORDER BY MIN(token.created_at) DESC
        "#,
    )
    .bind(current_user.id)
    .bind(now)
    .fetch_all(&state.db)
    .await?;

    let body: Vec<AuthorizedAppResponse> = rows
        .into_iter()
        .map(|row| AuthorizedAppResponse {
            id: row.id.to_string(),
            name: row.name,
            website: row.website,
            scopes: if row.scopes.is_empty() {
                Vec::new()
            } else {
                row.scopes.split_whitespace().map(str::to_string).collect()
            },
            created_at: to_mastodon_datetime(row.first_authorized_at),
        })
        .collect();

    Ok(Json(body).into_response())
}

/// `app/api/authorized_apps.py` の `revoke_authorized_app` を移植したもの。
async fn revoke_authorized_app(
    State(state): State<AppState>,
    current_user: CurrentUser,
    Path(app_id): Path<Uuid>,
) -> Result<Response, AppError> {
    let now = Utc::now();
    let result = sqlx::query(
        r#"
        UPDATE oauth_tokens
        SET revoked_at = $1
        WHERE application_id = $2 AND user_id = $3 AND revoked_at IS NULL
        "#,
    )
    .bind(now)
    .bind(app_id)
    .bind(current_user.id)
    .execute(&state.db)
    .await?;

    if result.rows_affected() == 0 {
        return Err(AppError::not_found("No active authorization found"));
    }

    Ok((StatusCode::OK, Json(json!({}))).into_response())
}
