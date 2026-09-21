//! `app/api/auth.py` のうち `GET /api/v1/accounts/verify_credentials`
//! (`verify_credentials`/`_credential_account_response`) のみを切り出した
//! もの。認証状態にある本人自身の情報を返すだけの単純な読み取り専用
//! エンドポイントで、ノートの可視性判定や連合配送を伴わないため、
//! Issue #1139 Stage 4 の他の項目(NoteResponse直列化パイプライン等)とは
//! 独立に進められる。`response_model` が指定されていないPython版と同じく、
//! 生の JSON オブジェクトをそのまま返す。

use axum::response::{IntoResponse, Response};
use axum::routing::get;
use axum::{extract::State, Json, Router};
use chrono::{DateTime, Utc};
use serde_json::{json, Value};
use uuid::Uuid;

use crate::auth::CurrentUser;
use crate::config::Config;
use crate::error::AppError;
use crate::follows::get_follow_counts;
use crate::hmac_sig::media_proxy_url;
use crate::mastodon_time::to_mastodon_datetime;
use crate::note_response::get_statuses_count;
use crate::shortcode::find_shortcodes;
use crate::state::AppState;

pub fn router() -> Router<AppState> {
    Router::new().route(
        "/api/v1/accounts/verify_credentials",
        get(verify_credentials),
    )
}

/// `MODERATOR_PERMISSIONS`(`app/services/role_service.py`)と同一。
const MODERATOR_PERMISSIONS: &[&str] = &[
    "users",
    "reports",
    "content",
    "domains",
    "federation",
    "emoji",
    "registrations",
    "announcements",
];

#[derive(sqlx::FromRow)]
struct CredentialRow {
    email: String,
    email_verified: bool,
    user_created_at: DateTime<Utc>,
    role: String,
    actor_id: Uuid,
    username: String,
    display_name: Option<String>,
    summary: Option<String>,
    ap_id: String,
    avatar_url: Option<String>,
    header_url: Option<String>,
    is_bot: bool,
    #[sqlx(rename = "type")]
    actor_type: String,
    manually_approves_followers: bool,
    discoverable: bool,
    fields: Option<Value>,
    also_known_as: Option<Value>,
    birthday: Option<chrono::NaiveDate>,
    is_cat: bool,
    avatar_focal_x: Option<f64>,
    avatar_focal_y: Option<f64>,
    header_focal_x: Option<f64>,
    header_focal_y: Option<f64>,
}

async fn fetch_credential_row(
    db: &sqlx::PgPool,
    user_id: Uuid,
) -> Result<Option<CredentialRow>, AppError> {
    let row = sqlx::query_as::<_, CredentialRow>(
        r#"
        SELECT u.email, u.email_verified, u.created_at AS user_created_at, u.role,
               a.id AS actor_id, a.username, a.display_name, a.summary, a.ap_id,
               a.avatar_url, a.header_url, a.is_bot, a.type,
               a.manually_approves_followers, a.discoverable, a.fields,
               a.also_known_as, a.birthday, a.is_cat,
               af.focal_x AS avatar_focal_x, af.focal_y AS avatar_focal_y,
               hf.focal_x AS header_focal_x, hf.focal_y AS header_focal_y
        FROM users u
        JOIN actors a ON a.id = u.actor_id
        LEFT JOIN drive_files af ON af.id = a.avatar_file_id
        LEFT JOIN drive_files hf ON hf.id = a.header_file_id
        WHERE u.id = $1
        "#,
    )
    .bind(user_id)
    .fetch_optional(db)
    .await?;
    Ok(row)
}

#[derive(sqlx::FromRow)]
struct RolePermissionsRow {
    permissions: Value,
}

/// `app.services.role_service.get_role` のうち `permissions` 列のみを移植。
async fn fetch_role_permissions(
    db: &sqlx::PgPool,
    role_name: &str,
) -> Result<Option<Value>, AppError> {
    let row: Option<RolePermissionsRow> =
        sqlx::query_as("SELECT permissions FROM roles WHERE name = $1")
            .bind(role_name)
            .fetch_optional(db)
            .await?;
    Ok(row.map(|r| r.permissions))
}

/// `str.capitalize()` (先頭大文字化+残りは小文字化) を移植したもの。
fn python_capitalize(s: &str) -> String {
    let mut chars = s.chars();
    match chars.next() {
        Some(first) => first.to_uppercase().collect::<String>() + &chars.as_str().to_lowercase(),
        None => String::new(),
    }
}

fn role_json(role: &str) -> Value {
    let id = match role {
        "admin" => "3",
        "moderator" => "2",
        _ => "-1",
    };
    let permissions = if role == "admin" { "65535" } else { "0" };
    let highlighted = matches!(role, "admin" | "moderator");
    json!({
        "id": id,
        "name": if role.is_empty() { String::new() } else { python_capitalize(role) },
        "permissions": permissions,
        "color": "",
        "highlighted": highlighted,
    })
}

async fn resolve_nekonoverse_permissions(
    db: &sqlx::PgPool,
    role: &str,
) -> Result<Vec<String>, AppError> {
    if role == "admin" {
        return Ok(MODERATOR_PERMISSIONS
            .iter()
            .map(|s| s.to_string())
            .collect());
    }
    if role != "user" {
        // is_staff (role != "user")
        if let Some(permissions) = fetch_role_permissions(db, role).await? {
            if let Some(map) = permissions.as_object() {
                let enabled: Vec<String> = map
                    .iter()
                    .filter(|(_, v)| v.as_bool().unwrap_or(false))
                    .map(|(k, _)| k.clone())
                    .collect();
                return Ok(enabled);
            }
        }
        return Ok(Vec::new());
    }
    Ok(Vec::new())
}

#[derive(sqlx::FromRow)]
struct EmojiRow {
    shortcode: String,
    url: String,
    static_url: Option<String>,
}

fn emoji_json(config: &Config, e: &EmojiRow) -> Value {
    let url = media_proxy_url(config, Some(&e.url), Some("emoji"), false);
    let static_url = match e.static_url.as_deref() {
        Some(su) if !su.is_empty() => media_proxy_url(config, Some(su), Some("emoji"), true),
        _ => media_proxy_url(config, Some(&e.url), Some("emoji"), true),
    };
    json!({ "shortcode": e.shortcode, "url": url, "static_url": static_url })
}

/// `_credential_account_response` の絵文字解決部分を移植したもの。
/// 対象は常にログイン中の本人(ローカルアクター)のため、ローカル絵文字
/// のみを解決する(リモートドメインへのフォールバックは不要)。
async fn resolve_local_emojis(
    db: &sqlx::PgPool,
    config: &Config,
    display_name: &str,
    note: &str,
    fields: Option<&Value>,
) -> Result<Vec<Value>, AppError> {
    let mut codes = std::collections::HashSet::new();
    find_shortcodes(display_name, &mut codes);
    find_shortcodes(note, &mut codes);
    if let Some(arr) = fields.and_then(|v| v.as_array()) {
        for f in arr {
            find_shortcodes(
                f.get("name").and_then(|v| v.as_str()).unwrap_or(""),
                &mut codes,
            );
            find_shortcodes(
                f.get("value").and_then(|v| v.as_str()).unwrap_or(""),
                &mut codes,
            );
        }
    }
    if codes.is_empty() {
        return Ok(Vec::new());
    }
    let codes_vec: Vec<String> = codes.into_iter().collect();
    let rows: Vec<EmojiRow> = sqlx::query_as(
        "SELECT shortcode, url, static_url FROM custom_emojis \
         WHERE shortcode = ANY($1) AND domain IS NULL",
    )
    .bind(&codes_vec)
    .fetch_all(db)
    .await?;
    Ok(rows.iter().map(|e| emoji_json(config, e)).collect())
}

/// `app/api/auth.py` の `verify_credentials`/`_credential_account_response`
/// を移植したもの。
async fn verify_credentials(
    State(state): State<AppState>,
    current_user: CurrentUser,
) -> Result<Response, AppError> {
    let row = fetch_credential_row(&state.db, current_user.id)
        .await?
        .ok_or_else(|| AppError::new(axum::http::StatusCode::UNAUTHORIZED, "User not found"))?;

    let (followers_count, following_count) =
        get_follow_counts(&state.db, &state.redis, row.actor_id).await?;
    let statuses_count = get_statuses_count(&state.db, &state.redis, row.actor_id).await?;

    let avatar_proxy = media_proxy_url(
        &state.config,
        row.avatar_url.as_deref(),
        Some("avatar"),
        false,
    );
    let avatar = if avatar_proxy.is_empty() {
        format!("{}/default-avatar.svg", state.config.server_url())
    } else {
        avatar_proxy
    };
    let avatar_static_proxy = media_proxy_url(
        &state.config,
        row.avatar_url.as_deref(),
        Some("avatar"),
        true,
    );
    let avatar_static = if avatar_static_proxy.is_empty() {
        avatar.clone()
    } else {
        avatar_static_proxy
    };
    let header = media_proxy_url(&state.config, row.header_url.as_deref(), None, false);

    let display_name = row.display_name.clone().unwrap_or_default();
    let note = row.summary.clone().unwrap_or_default();
    let fields: Vec<Value> = row
        .fields
        .as_ref()
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .map(|f| {
                    json!({
                        "name": f.get("name").and_then(|v| v.as_str()).unwrap_or(""),
                        "value": f.get("value").and_then(|v| v.as_str()).unwrap_or(""),
                        "verified_at": Value::Null,
                    })
                })
                .collect()
        })
        .unwrap_or_default();
    let source_fields: Vec<Value> = row
        .fields
        .as_ref()
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .map(|f| {
                    json!({
                        "name": f.get("name").and_then(|v| v.as_str()).unwrap_or(""),
                        "value": f.get("value").and_then(|v| v.as_str()).unwrap_or(""),
                    })
                })
                .collect()
        })
        .unwrap_or_default();

    let emojis = resolve_local_emojis(
        &state.db,
        &state.config,
        &display_name,
        &note,
        row.fields.as_ref(),
    )
    .await?;

    let nekonoverse_permissions = resolve_nekonoverse_permissions(&state.db, &row.role).await?;

    let avatar_focal = match (row.avatar_focal_x, row.avatar_focal_y) {
        (Some(x), Some(y)) => json!({ "x": x, "y": y }),
        _ => Value::Null,
    };
    let header_focal = match (row.header_focal_x, row.header_focal_y) {
        (Some(x), Some(y)) => json!({ "x": x, "y": y }),
        _ => Value::Null,
    };

    let data = json!({
        "id": row.actor_id.to_string(),
        "username": row.username,
        "acct": row.username,
        "display_name": display_name,
        "note": note,
        "uri": row.ap_id,
        "avatar": avatar,
        "avatar_static": avatar_static,
        "header": header,
        "header_static": header,
        "url": format!("{}/@{}", state.config.server_url(), row.username),
        "email": row.email,
        "email_verified": row.email_verified,
        "created_at": to_mastodon_datetime(row.user_created_at),
        "bot": row.is_bot,
        "group": row.actor_type == "Group",
        "locked": row.manually_approves_followers,
        "discoverable": row.discoverable,
        "followers_count": followers_count,
        "following_count": following_count,
        "statuses_count": statuses_count,
        "last_status_at": Value::Null,
        "fields": fields,
        "emojis": emojis,
        "source": {
            "privacy": "public",
            "sensitive": false,
            "language": "",
            "note": row.summary.clone().unwrap_or_default(),
            "fields": source_fields,
        },
        "avatar_url": row.avatar_url.clone().unwrap_or_else(|| "/default-avatar.svg".to_string()),
        "header_url": row.header_url,
        "avatar_focal": avatar_focal,
        "header_focal": header_focal,
        "summary": row.summary,
        "birthday": row.birthday.map(|d| d.to_string()),
        "is_cat": row.is_cat,
        "is_bot": row.is_bot,
        "also_known_as": row.also_known_as.unwrap_or_else(|| json!([])),
        "role": role_json(&row.role),
        "nekonoverse_permissions": nekonoverse_permissions,
    });

    Ok(Json(data).into_response())
}
