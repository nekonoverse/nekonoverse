use axum::extract::State;
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use axum::{Json, Router};
use chrono::{Duration, Utc};
use redis::AsyncCommands;
use serde_json::{json, Value};
use std::collections::HashMap;

use crate::error::AppError;
use crate::state::AppState;

/// `app.__init__.VERSION` (`__version__ = "20260919-1"`) と同期させること。
/// Python 側は `GIT_VERSION` ファイル/git コマンドで develop ビルドに
/// `+git-<hash>` サフィックスを付加するが、backend-rs は別イメージ・別
/// バイナリのためこの付加ロジックまでは再現せず、リリースバージョンの
/// 文字列のみを返す。
const NODE_VERSION: &str = "20260919-1";

const SETTINGS_CACHE_TTL_SECS: u64 = 300;

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/.well-known/nodeinfo", get(nodeinfo_discovery))
        .route("/nodeinfo/2.0", get(nodeinfo))
}

/// `activitypub/nodeinfo.py` の `nodeinfo_discovery` を移植したもの。
async fn nodeinfo_discovery(State(state): State<AppState>) -> Response {
    let server_url = state.config.server_url();
    Json(json!({
        "links": [{
            "rel": "http://nodeinfo.diaspora.software/ns/schema/2.0",
            "href": format!("{server_url}/nodeinfo/2.0"),
        }]
    }))
    .into_response()
}

/// `app.services.server_settings_service.get_settings_batch` を移植したもの。
/// Valkeyキャッシュ (`setting:{key}`, 値なしは `__NULL__` センチネル) を優先し、
/// ミス分のみDBから1クエリで取得してキャッシュに書き戻す (TTL 300秒)。
async fn get_settings_batch(
    db: &sqlx::PgPool,
    redis: &redis::aio::ConnectionManager,
    keys: &[&str],
) -> Result<HashMap<String, Option<String>>, AppError> {
    let mut conn = redis.clone();
    let mut result: HashMap<String, Option<String>> = HashMap::new();

    let cache_keys: Vec<String> = keys.iter().map(|k| format!("setting:{k}")).collect();
    let cached_values: Vec<Option<String>> = conn.mget(&cache_keys).await?;

    let mut missing_keys: Vec<&str> = Vec::new();
    for (key, cached) in keys.iter().zip(cached_values.iter()) {
        match cached {
            Some(v) if v == "__NULL__" => {
                result.insert((*key).to_string(), None);
            }
            Some(v) => {
                result.insert((*key).to_string(), Some(v.clone()));
            }
            None => missing_keys.push(key),
        }
    }

    if !missing_keys.is_empty() {
        let missing_owned: Vec<String> = missing_keys.iter().map(|s| s.to_string()).collect();
        let rows: Vec<(String, Option<String>)> =
            sqlx::query_as("SELECT key, value FROM server_settings WHERE key = ANY($1)")
                .bind(&missing_owned)
                .fetch_all(db)
                .await?;
        let db_settings: HashMap<String, Option<String>> = rows.into_iter().collect();

        let mut pipe = redis::pipe();
        for key in &missing_keys {
            let value = db_settings.get(*key).cloned().flatten();
            result.insert((*key).to_string(), value.clone());
            pipe.set_ex(
                format!("setting:{key}"),
                value.unwrap_or_else(|| "__NULL__".to_string()),
                SETTINGS_CACHE_TTL_SECS,
            );
        }
        let _: () = pipe.query_async(&mut conn).await?;
    }

    Ok(result)
}

/// `activitypub/nodeinfo.py` の `nodeinfo` を移植したもの。
async fn nodeinfo(State(state): State<AppState>) -> Result<Response, AppError> {
    let user_count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM actors WHERE domain IS NULL")
        .fetch_one(&state.db)
        .await?;

    let post_count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM notes WHERE local = true")
        .fetch_one(&state.db)
        .await?;

    let now = Utc::now();
    let halfyear_ago = now - Duration::days(180);
    let month_ago = now - Duration::days(30);

    let (active_halfyear, active_month): (i64, i64) = sqlx::query_as(
        r#"
        SELECT
            COUNT(DISTINCT actor_id) AS halfyear,
            COUNT(DISTINCT CASE WHEN published >= $2 THEN actor_id END) AS month
        FROM notes
        WHERE local = true
          AND actor_id IN (SELECT id FROM actors WHERE domain IS NULL)
          AND published >= $1
          AND deleted_at IS NULL
        "#,
    )
    .bind(halfyear_ago)
    .bind(month_ago)
    .fetch_one(&state.db)
    .await?;

    // サーバー設定の取得は失敗してもnodeinfo全体を失敗させない (Python版のtry/exceptと同じ)。
    let setting_keys = [
        "registration_mode",
        "registration_open",
        "server_name",
        "server_description",
        "server_icon_url",
        "server_theme_color",
        "katex_enabled",
    ];

    let mut node_name = "Nekonoverse".to_string();
    let mut node_description = "A cat-friendly ActivityPub server".to_string();
    let mut node_icon_url: Option<String> = None;
    let mut node_theme_color: Option<String> = None;
    let mut open_registrations = state.config.registration_open;
    let mut features = vec!["emoji_reactions".to_string()];

    if let Ok(s) = get_settings_batch(&state.db, &state.redis, &setting_keys).await {
        match s.get("registration_mode").and_then(|v| v.as_deref()) {
            Some(mode) => {
                open_registrations = mode == "open" || mode == "approval";
            }
            None => {
                if let Some(reg) = s.get("registration_open").and_then(|v| v.as_deref()) {
                    open_registrations = reg == "true";
                }
            }
        }
        if let Some(name) = s.get("server_name").and_then(|v| v.as_deref()) {
            if !name.is_empty() {
                node_name = name.to_string();
            }
        }
        if let Some(desc) = s.get("server_description").and_then(|v| v.as_deref()) {
            if !desc.is_empty() {
                node_description = desc.to_string();
            }
        }
        node_icon_url = s
            .get("server_icon_url")
            .and_then(|v| v.as_deref())
            .filter(|v| !v.is_empty())
            .map(String::from);
        node_theme_color = s
            .get("server_theme_color")
            .and_then(|v| v.as_deref())
            .filter(|v| !v.is_empty())
            .map(String::from);
        if s.get("katex_enabled").and_then(|v| v.as_deref()) == Some("true") {
            features.push("katex".to_string());
        }
    }

    let mut metadata = json!({
        "nodeName": node_name,
        "nodeDescription": node_description,
        "features": features,
    });
    if let Some(icon_url) = node_icon_url {
        metadata["iconUrl"] = Value::String(icon_url);
    }
    if let Some(theme_color) = node_theme_color {
        metadata["themeColor"] = Value::String(theme_color);
    }

    Ok(Json(json!({
        "version": "2.0",
        "software": {"name": "nekonoverse", "version": NODE_VERSION},
        "protocols": ["activitypub"],
        "services": {"inbound": [], "outbound": []},
        "openRegistrations": open_registrations,
        "usage": {
            "users": {
                "total": user_count,
                "activeHalfyear": active_halfyear,
                "activeMonth": active_month,
            },
            "localPosts": post_count,
        },
        "metadata": metadata,
    }))
    .into_response())
}
