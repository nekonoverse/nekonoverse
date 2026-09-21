//! `app/api/auth.py` のうち `GET /api/v1/accounts/verify_credentials`
//! (`verify_credentials`/`_credential_account_response`) と TOTP 二要素認証系
//! (`/auth/totp/setup`/`enable`/`disable`/`verify`/`status`) を切り出したもの。
//! 前者は認証状態にある本人自身の情報を返すだけの単純な読み取り専用エンドポイント
//! で、Issue #1139 Stage 4 の他の項目(NoteResponse直列化パイプライン等)とは
//! 独立に進められる。`response_model` が指定されていないPython版と同じく、
//! 生の JSON オブジェクトをそのまま返す。
//!
//! TOTP系は `app/services/totp_service.py`(`totp.rs`)に依存する。Python版の
//! secretは PBKDF2-HMAC-SHA256(60万回)から導出したFernetキーで暗号化して
//! 保存されており、Rust側もPython生成のオラクル値を使ったテストで互換性を
//! 検証済み(`totp.rs`参照)。`totp_verify`のみ未認証(ログイン処理の後半で
//! 発行される`totp_pending:{token}`を経由する2段階目)で、成功時に
//! `session.rs`(新設)でセッションCookieを発行する。`POST /auth/login`
//! 本体(1段階目、TOTP非対象ユーザーの通常ログイン)は未移植のまま
//! Python側に残るが、Valkeyのセッション/保留トークンは両サービスで共有
//! しているため、Python側のログインが発行した`totp_pending`トークンを
//! Rust側の`totp_verify`が消費する形で問題なく連携する。
//! クライアントIP解決: Python版は`request.client.host`(uvicornの生TCP peer、
//! `--proxy-headers`未使用のため実運用ではnginxコンテナのIPか、本番のUDS
//! バインドでは`None`→"unknown"になる、実質機能していない値)をそのまま
//! 記録するが、Rust版はnginxが全リクエストに付与済みの`X-Real-IP`ヘッダーを
//! 読む安全側の改善とする(`totp_secret`のCSPRNG生成と同じ判断: 新規に記録する
//! 監査ログの値であり、既存データとの互換性やテストオラクルとの比較対象では
//! ないため)。

use axum::body::Bytes;
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{extract::State, Json, Router};
use chrono::{DateTime, Utc};
use serde::Deserialize;
use serde_json::{json, Value};
use uuid::Uuid;

use crate::auth::CurrentUser;
use crate::config::Config;
use crate::error::AppError;
use crate::follows::get_follow_counts;
use crate::hmac_sig::media_proxy_url;
use crate::mastodon_time::to_mastodon_datetime;
use crate::note_response::get_statuses_count;
use crate::session::{create_session_with_metadata, record_login};
use crate::shortcode::find_shortcodes;
use crate::state::AppState;
use crate::totp;

pub fn router() -> Router<AppState> {
    Router::new()
        .route(
            "/api/v1/accounts/verify_credentials",
            get(verify_credentials),
        )
        .route("/api/v1/auth/totp/setup", post(totp_setup))
        .route("/api/v1/auth/totp/enable", post(totp_enable))
        .route("/api/v1/auth/totp/disable", post(totp_disable))
        .route("/api/v1/auth/totp/verify", post(totp_verify))
        .route("/api/v1/auth/totp/status", get(totp_status))
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

fn parse_json_body<T: serde::de::DeserializeOwned>(body: &Bytes) -> Result<T, AppError> {
    serde_json::from_slice(body).map_err(|e| {
        AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            format!("Invalid request body: {e}"),
        )
    })
}

/// bcryptはCPUバウンドの同期処理のため、Python版が`asyncio.to_thread`で
/// イベントループのブロックを避けているのと同じ意図で、axumのワーカー
/// スレッドを塞がないよう`spawn_blocking`に逃がす。
async fn blocking<T: Send + 'static>(f: impl FnOnce() -> T + Send + 'static) -> T {
    tokio::task::spawn_blocking(f)
        .await
        .expect("blocking task panicked")
}

#[derive(Deserialize)]
struct TotpSetupRequest {
    password: String,
}

#[derive(Deserialize)]
struct TotpEnableRequest {
    code: String,
}

#[derive(Deserialize)]
struct TotpDisableRequest {
    password: String,
}

#[derive(Deserialize)]
struct TotpVerifyRequest {
    totp_token: String,
    code: String,
}

/// `app.api.auth.totp_setup` を移植したもの。
async fn totp_setup(
    State(state): State<AppState>,
    current_user: CurrentUser,
    body: Bytes,
) -> Result<Response, AppError> {
    let payload: TotpSetupRequest = parse_json_body(&body)?;

    #[derive(sqlx::FromRow)]
    struct Row {
        totp_enabled: bool,
        password_hash: String,
    }
    let row: Row = sqlx::query_as("SELECT totp_enabled, password_hash FROM users WHERE id = $1")
        .bind(current_user.id)
        .fetch_one(&state.db)
        .await?;

    if row.totp_enabled {
        return Err(AppError::new(
            StatusCode::BAD_REQUEST,
            "TOTP is already enabled",
        ));
    }
    let password = payload.password.clone();
    let password_hash = row.password_hash.clone();
    let valid = blocking(move || bcrypt::verify(&password, &password_hash).unwrap_or(false)).await;
    if !valid {
        return Err(AppError::new(StatusCode::UNAUTHORIZED, "Invalid password"));
    }

    let secret = totp::generate_totp_secret();
    let secret_key = state.config.secret_key.clone();
    let secret_for_encrypt = secret.clone();
    let iterations = state.config.totp_pbkdf2_iterations;
    let encrypted =
        blocking(move || totp::encrypt_secret(&secret_key, &secret_for_encrypt, iterations))
            .await?;
    sqlx::query("UPDATE users SET totp_secret = $1 WHERE id = $2")
        .bind(&encrypted)
        .bind(current_user.id)
        .execute(&state.db)
        .await?;

    let username: String = sqlx::query_scalar("SELECT username FROM actors WHERE id = $1")
        .bind(current_user.actor_id)
        .fetch_one(&state.db)
        .await?;
    let issuer = format!("Nekonoverse ({})", state.config.domain);
    let uri = totp::generate_provisioning_uri(&secret, &username, &issuer);

    Ok(Json(json!({ "secret": secret, "provisioning_uri": uri })).into_response())
}

/// `app.api.auth.totp_enable` を移植したもの。
async fn totp_enable(
    State(state): State<AppState>,
    current_user: CurrentUser,
    body: Bytes,
) -> Result<Response, AppError> {
    let payload: TotpEnableRequest = parse_json_body(&body)?;

    #[derive(sqlx::FromRow)]
    struct Row {
        totp_enabled: bool,
        totp_secret: Option<String>,
        last_totp_counter: Option<i64>,
    }
    let row: Row = sqlx::query_as(
        "SELECT totp_enabled, totp_secret, last_totp_counter FROM users WHERE id = $1",
    )
    .bind(current_user.id)
    .fetch_one(&state.db)
    .await?;

    if row.totp_enabled {
        return Err(AppError::new(
            StatusCode::BAD_REQUEST,
            "TOTP is already enabled",
        ));
    }
    let Some(encrypted_secret) = row.totp_secret else {
        return Err(AppError::new(
            StatusCode::BAD_REQUEST,
            "Call /auth/totp/setup first",
        ));
    };

    let secret_key = state.config.secret_key.clone();
    let iterations = state.config.totp_pbkdf2_iterations;
    let secret =
        blocking(move || totp::decrypt_secret(&secret_key, &encrypted_secret, iterations)).await?;
    let Some(matched_counter) =
        totp::verify_totp_code_with_counter(&secret, &payload.code, row.last_totp_counter, None)
    else {
        return Err(AppError::new(StatusCode::BAD_REQUEST, "Invalid TOTP code"));
    };
    if !totp::advance_last_totp_counter(&state.db, current_user.id, matched_counter).await? {
        // 並列リクエストが先に同じカウンタを記録 — リプレイとして拒否。
        return Err(AppError::new(StatusCode::BAD_REQUEST, "Invalid TOTP code"));
    }

    let recovery_codes = totp::generate_recovery_codes();
    let codes_to_hash = recovery_codes.clone();
    let cost = state.config.bcrypt_cost;
    let hashed = blocking(move || totp::hash_recovery_codes(&codes_to_hash, cost)).await?;

    sqlx::query("UPDATE users SET totp_enabled = true, totp_recovery_codes = $1 WHERE id = $2")
        .bind(sqlx::types::Json(&hashed))
        .bind(current_user.id)
        .execute(&state.db)
        .await?;

    Ok(Json(json!({ "recovery_codes": recovery_codes })).into_response())
}

/// `app.api.auth.totp_disable` を移植したもの。
async fn totp_disable(
    State(state): State<AppState>,
    current_user: CurrentUser,
    body: Bytes,
) -> Result<Response, AppError> {
    let payload: TotpDisableRequest = parse_json_body(&body)?;

    #[derive(sqlx::FromRow)]
    struct Row {
        totp_enabled: bool,
        password_hash: String,
    }
    let row: Row = sqlx::query_as("SELECT totp_enabled, password_hash FROM users WHERE id = $1")
        .bind(current_user.id)
        .fetch_one(&state.db)
        .await?;

    if !row.totp_enabled {
        return Err(AppError::new(
            StatusCode::BAD_REQUEST,
            "TOTP is not enabled",
        ));
    }
    // Python版はここでのみ無効パスワードを400で返す (setup/loginは401)。非対称
    // だがPython版の実際の契約であり、そのまま再現する。
    let password = payload.password.clone();
    let password_hash = row.password_hash.clone();
    let valid = blocking(move || bcrypt::verify(&password, &password_hash).unwrap_or(false)).await;
    if !valid {
        return Err(AppError::new(StatusCode::BAD_REQUEST, "Invalid password"));
    }

    sqlx::query(
        "UPDATE users SET totp_enabled = false, totp_secret = NULL, totp_recovery_codes = NULL \
         WHERE id = $1",
    )
    .bind(current_user.id)
    .execute(&state.db)
    .await?;

    Ok(Json(json!({ "ok": true })).into_response())
}

/// `app.api.auth.totp_status` を移植したもの。
async fn totp_status(
    State(state): State<AppState>,
    current_user: CurrentUser,
) -> Result<Response, AppError> {
    let totp_enabled: bool = sqlx::query_scalar("SELECT totp_enabled FROM users WHERE id = $1")
        .bind(current_user.id)
        .fetch_one(&state.db)
        .await?;
    Ok(Json(json!({ "totp_enabled": totp_enabled })).into_response())
}

const TOTP_MAX_ATTEMPTS: i64 = 5;
const TOTP_LOCKOUT_TTL: i64 = 300;

/// トークン単位のブルートフォース失敗を記録して401を返す
/// (`totp_verify`の3つの失敗経路 — 無効コード/無効カウンタ再利用/
/// 無効リカバリーコード — で共通に呼ぶ)。
async fn reject_totp_verify(
    state: &AppState,
    attempts_key: &str,
    user_id: Uuid,
) -> Result<Response, AppError> {
    use redis::AsyncCommands;
    let mut redis = state.redis.clone();
    let _: i64 = redis.incr(attempts_key, 1).await?;
    let _: () = redis.expire(attempts_key, TOTP_LOCKOUT_TTL).await?;
    totp::record_totp_failure(&state.redis, user_id).await?;
    Err(AppError::new(StatusCode::UNAUTHORIZED, "Invalid TOTP code"))
}

/// `app.api.auth.totp_verify` を移植したもの。ログイン1段階目(未移植、
/// Python側に残る`/auth/login`)が発行した保留トークンを消費し、成功時に
/// セッションCookieを発行する(モジュール冒頭のコメント参照)。
async fn totp_verify(
    State(state): State<AppState>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<Response, AppError> {
    use redis::AsyncCommands;

    let payload: TotpVerifyRequest = parse_json_body(&body)?;
    let mut redis = state.redis.clone();

    let attempts_key = format!("totp_attempts:{}", payload.totp_token);
    let attempts: Option<i64> = redis.get(&attempts_key).await?;
    if attempts.is_some_and(|a| a >= TOTP_MAX_ATTEMPTS) {
        return Err(AppError::new(
            StatusCode::TOO_MANY_REQUESTS,
            "Too many TOTP attempts. Please wait 5 minutes and try again.",
        ));
    }

    let pending_key = format!("totp_pending:{}", payload.totp_token);
    let user_id_str: Option<String> = redis.get(&pending_key).await?;
    let Some(user_id_str) = user_id_str else {
        return Err(AppError::new(
            StatusCode::UNAUTHORIZED,
            "Invalid or expired TOTP token",
        ));
    };
    let user_id = Uuid::parse_str(&user_id_str)
        .map_err(|_| AppError::new(StatusCode::UNAUTHORIZED, "Invalid or expired TOTP token"))?;

    #[derive(sqlx::FromRow)]
    struct Row {
        totp_secret: Option<String>,
        totp_recovery_codes: Option<sqlx::types::Json<Vec<String>>>,
        last_totp_counter: Option<i64>,
    }
    let row: Option<Row> = sqlx::query_as(
        "SELECT totp_secret, totp_recovery_codes, last_totp_counter FROM users WHERE id = $1",
    )
    .bind(user_id)
    .fetch_optional(&state.db)
    .await?;
    let Some(row) = row else {
        return Err(AppError::new(StatusCode::UNAUTHORIZED, "User not found"));
    };

    if totp::is_totp_locked(&state.redis, user_id).await? {
        return Err(AppError::new(
            StatusCode::TOO_MANY_REQUESTS,
            "Too many TOTP attempts. Please wait and try again.",
        ));
    }

    let Some(encrypted_secret) = row.totp_secret else {
        return reject_totp_verify(&state, &attempts_key, user_id).await;
    };
    let secret_key = state.config.secret_key.clone();
    let iterations = state.config.totp_pbkdf2_iterations;
    let secret =
        blocking(move || totp::decrypt_secret(&secret_key, &encrypted_secret, iterations)).await?;
    let totp_code: String = payload.code.trim().chars().filter(|c| *c != '-').collect();

    let matched_counter =
        totp::verify_totp_code_with_counter(&secret, &totp_code, row.last_totp_counter, None);
    if let Some(matched_counter) = matched_counter {
        if !totp::advance_last_totp_counter(&state.db, user_id, matched_counter).await? {
            return reject_totp_verify(&state, &attempts_key, user_id).await;
        }
    } else if let Some(sqlx::types::Json(recovery_codes)) = &row.totp_recovery_codes {
        if recovery_codes.is_empty() {
            return reject_totp_verify(&state, &attempts_key, user_id).await;
        }
        let candidate = payload.code.trim().to_string();
        let codes_to_check = recovery_codes.clone();
        let (valid, remaining) =
            blocking(move || totp::verify_recovery_code(&candidate, &codes_to_check)).await;
        if !valid {
            return reject_totp_verify(&state, &attempts_key, user_id).await;
        }
        sqlx::query("UPDATE users SET totp_recovery_codes = $1 WHERE id = $2")
            .bind(sqlx::types::Json(&remaining))
            .bind(user_id)
            .execute(&state.db)
            .await?;
        // Defense-in-depth: リカバリー認証成功時も TOTP カウンタを現在ステップまで
        // 進めておく (戻り値は無視 — Python版と同じくベストエフォート)。
        let _ = totp::advance_last_totp_counter(&state.db, user_id, totp::current_time_step(None))
            .await;
    } else {
        return reject_totp_verify(&state, &attempts_key, user_id).await;
    }

    let _: i64 = redis.del(&attempts_key).await?;
    totp::clear_totp_failures(&state.redis, user_id).await?;
    let _: i64 = redis.del(&pending_key).await?;

    let client_ip = headers
        .get("x-real-ip")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("unknown");
    let user_agent = headers
        .get(axum::http::header::USER_AGENT)
        .and_then(|v| v.to_str().ok());

    let session_id = generate_session_id();
    create_session_with_metadata(&state.redis, user_id, &session_id, client_ip, user_agent).await?;
    record_login(&state.db, user_id, client_ip, user_agent, "totp").await?;

    let secure_attr = if state.config.use_https {
        "; Secure"
    } else {
        ""
    };
    let cookie = format!(
        "nekonoverse_session={session_id}; HttpOnly; Max-Age=2592000; Path=/; SameSite=lax{secure_attr}"
    );

    let mut response = Json(json!({ "ok": true })).into_response();
    response.headers_mut().insert(
        axum::http::header::SET_COOKIE,
        axum::http::HeaderValue::from_str(&cookie).map_err(|_| {
            AppError::new(StatusCode::INTERNAL_SERVER_ERROR, "Internal server error")
        })?,
    );
    Ok(response)
}

/// `secrets.token_urlsafe(32)` 相当 (32ランダムバイトをURLセーフBase64、パディングなし)。
fn generate_session_id() -> String {
    use base64::engine::general_purpose::URL_SAFE_NO_PAD;
    use base64::Engine;
    use rand::RngCore;
    let mut bytes = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut bytes);
    URL_SAFE_NO_PAD.encode(bytes)
}
