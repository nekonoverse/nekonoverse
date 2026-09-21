//! `app/activitypub/routes.py` の `get_actor`/`get_followers_collection`/
//! `get_following_collection` を移植したもの。`get_actor_by_username(db,
//! username, domain=None)` はローカルアクターしか返さないため、`render_actor`
//! のリモートアクター分岐(保存済みURL列をそのまま使う側)は不要 — これらの
//! エンドポイントに関する限りアクターは常にローカルである。`get_outbox`/
//! `get_featured`(いずれも`render_note`が必要で難易度が上がる)は別PRで扱う。

use axum::extract::{Path, Query, State};
use axum::http::{header, HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use axum::Router;
use chrono::{DateTime, NaiveDate, Utc};
use serde::Deserialize;
use serde_json::{json, Value};
use uuid::Uuid;

use crate::activitypub::{render_ordered_collection, render_ordered_collection_page, AP_CONTEXT};
use crate::error::AppError;
use crate::state::AppState;

const AP_CONTENT_TYPE: &str = "application/activity+json; charset=utf-8";

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/users/:username", get(get_actor))
        .route("/users/:username/followers", get(get_followers_collection))
        .route("/users/:username/following", get(get_following_collection))
}

/// `page: bool = False` (FastAPI) を移植したクエリパラメータ。
#[derive(Deserialize)]
struct PageQuery {
    #[serde(default)]
    page: bool,
}

/// `get_actor_by_username(db, username, domain=None)` のうち、Collection系
/// エンドポイントが必要とするactor idのみを取得する軽量版。
async fn fetch_local_actor_id(db: &sqlx::PgPool, username: &str) -> Result<Uuid, AppError> {
    sqlx::query_scalar("SELECT id FROM actors WHERE username = $1 AND domain IS NULL")
        .bind(username.to_lowercase())
        .fetch_optional(db)
        .await?
        .ok_or_else(|| AppError::not_found("Actor not found"))
}

#[derive(sqlx::FromRow)]
struct ActorRow {
    username: String,
    #[sqlx(rename = "type")]
    actor_type: String,
    display_name: Option<String>,
    summary: Option<String>,
    avatar_url: Option<String>,
    header_url: Option<String>,
    public_key_pem: String,
    public_key_ed25519_multibase: Option<String>,
    is_cat: bool,
    manually_approves_followers: bool,
    discoverable: bool,
    birthday: Option<NaiveDate>,
    require_signin_to_view: bool,
    make_notes_followers_only_before: Option<i64>,
    make_notes_hidden_before: Option<i64>,
    moved_to_ap_id: Option<String>,
    also_known_as: Option<Value>,
    fields: Option<Value>,
    created_at: DateTime<Utc>,
    deleted_at: Option<DateTime<Utc>>,
    suspended_at: Option<DateTime<Utc>>,
    ap_id: String,
}

/// `app.activitypub.routes.is_ap_request` を移植したもの
/// (大文字小文字を区別する部分文字列一致、Python版と同一)。
fn is_ap_request(headers: &HeaderMap) -> bool {
    let accept = headers
        .get(header::ACCEPT)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");
    accept.contains("application/activity+json") || accept.contains("application/ld+json")
}

/// `app/activitypub/renderer.py` の `_iso_z` を移植したもの
/// (マイクロ秒6桁 + 末尾 `Z`、タイムゾーンオフセット表記は使わない)。
fn iso_z(dt: DateTime<Utc>) -> String {
    dt.format("%Y-%m-%dT%H:%M:%S%.6fZ").to_string()
}

fn ap_json_response(status: StatusCode, value: &Value) -> Response {
    (
        status,
        [(header::CONTENT_TYPE, AP_CONTENT_TYPE)],
        value.to_string(),
    )
        .into_response()
}

/// `app/activitypub/routes.py` の `get_actor` を移植したもの。
async fn get_actor(
    State(state): State<AppState>,
    Path(username): Path<String>,
    headers: HeaderMap,
) -> Result<Response, AppError> {
    let row = sqlx::query_as::<_, ActorRow>(
        r#"
        SELECT username, type, display_name, summary, avatar_url, header_url,
               public_key_pem, public_key_ed25519_multibase, is_cat,
               manually_approves_followers, discoverable, birthday,
               require_signin_to_view, make_notes_followers_only_before,
               make_notes_hidden_before, moved_to_ap_id, also_known_as, fields,
               created_at, deleted_at, suspended_at, ap_id
        FROM actors
        WHERE username = $1 AND domain IS NULL
        "#,
    )
    .bind(username.to_lowercase())
    .fetch_optional(&state.db)
    .await?
    .ok_or_else(|| AppError::not_found("Actor not found"))?;

    let ap_request = is_ap_request(&headers);

    if row.deleted_at.is_some() {
        if ap_request {
            let tombstone = json!({
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": row.ap_id,
                "type": "Tombstone",
            });
            return Ok(ap_json_response(StatusCode::GONE, &tombstone));
        }
        return Err(AppError::new(StatusCode::GONE, "Gone"));
    }

    if row.suspended_at.is_some() {
        return Err(AppError::new(StatusCode::GONE, "Gone"));
    }

    if !ap_request {
        return Ok((
            StatusCode::FOUND,
            [(header::LOCATION, format!("/@{username}"))],
            "",
        )
            .into_response());
    }

    Ok(ap_json_response(
        StatusCode::OK,
        &render_local_actor(&state, &row),
    ))
}

/// `app/activitypub/renderer.py` の `render_actor` を移植したもの
/// (`actor.domain is None` のローカル分岐のみ)。
fn render_local_actor(state: &AppState, row: &ActorRow) -> Value {
    let server_url = state.config.server_url();
    let actor_url = format!("{server_url}/users/{}", row.username);

    let mut data = json!({
        "@context": AP_CONTEXT.clone(),
        "id": actor_url,
        "type": row.actor_type,
        "preferredUsername": row.username,
        "name": row.display_name.clone().unwrap_or_else(|| row.username.clone()),
        "inbox": format!("{actor_url}/inbox"),
        "outbox": format!("{actor_url}/outbox"),
        "url": format!("{server_url}/@{}", row.username),
        "published": iso_z(row.created_at),
        "manuallyApprovesFollowers": row.manually_approves_followers,
        "discoverable": row.discoverable,
        "publicKey": {
            "id": format!("{actor_url}#main-key"),
            "owner": actor_url,
            "publicKeyPem": row.public_key_pem,
        },
        "endpoints": { "sharedInbox": format!("{server_url}/inbox") },
        "isCat": row.is_cat,
        "followers": format!("{actor_url}/followers"),
        "following": format!("{actor_url}/following"),
        "featured": format!("{actor_url}/featured"),
    });

    if let Some(multibase) = &row.public_key_ed25519_multibase {
        data["assertionMethod"] = json!([{
            "id": format!("{actor_url}#ed25519-key"),
            "type": "Multikey",
            "controller": actor_url,
            "publicKeyMultibase": multibase,
        }]);
    }
    if let Some(summary) = &row.summary {
        data["summary"] = json!(summary);
    }
    if let Some(avatar) = &row.avatar_url {
        data["icon"] = json!({ "type": "Image", "url": avatar });
    }
    if let Some(header_url) = &row.header_url {
        data["image"] = json!({ "type": "Image", "url": header_url });
    }
    if let Some(fields) = row.fields.as_ref().and_then(|v| v.as_array()) {
        if !fields.is_empty() {
            let attachment: Vec<Value> = fields
                .iter()
                .map(|f| {
                    json!({
                        "type": "PropertyValue",
                        "name": f.get("name").and_then(|v| v.as_str()).unwrap_or(""),
                        "value": f.get("value").and_then(|v| v.as_str()).unwrap_or(""),
                    })
                })
                .collect();
            data["attachment"] = json!(attachment);
        }
    }
    if let Some(birthday) = row.birthday {
        data["vcard:bday"] = json!(birthday.to_string());
    }
    if let Some(moved) = &row.moved_to_ap_id {
        data["movedTo"] = json!(moved);
    }
    if let Some(aka) = row.also_known_as.as_ref().and_then(|v| v.as_array()) {
        if !aka.is_empty() {
            data["alsoKnownAs"] = json!(aka);
        }
    }
    if row.require_signin_to_view {
        data["_misskey_requireSigninToViewContents"] = json!(true);
    }
    if let Some(v) = row.make_notes_followers_only_before {
        data["_misskey_makeNotesFollowersOnlyBefore"] = json!(v);
    }
    if let Some(v) = row.make_notes_hidden_before {
        data["_misskey_makeNotesHiddenBefore"] = json!(v);
    }

    data
}

/// `app/activitypub/routes.py` の `get_followers_collection` を移植したもの。
/// Content Negotiationはせず常にAP JSONを返す(Python版もis_ap_request判定なし)。
async fn get_followers_collection(
    State(state): State<AppState>,
    Path(username): Path<String>,
    Query(query): Query<PageQuery>,
) -> Result<Response, AppError> {
    let actor_id = fetch_local_actor_id(&state.db, &username).await?;
    let collection_url = format!("{}/users/{username}/followers", state.config.server_url());

    if !query.page {
        let total: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM followers WHERE following_id = $1 AND accepted = true",
        )
        .bind(actor_id)
        .fetch_one(&state.db)
        .await?;
        let body = render_ordered_collection(
            &collection_url,
            total,
            &format!("{collection_url}?page=true"),
        );
        return Ok(ap_json_response(StatusCode::OK, &body));
    }

    // M-10 (Python版コメント): 40件ずつのページネーション。`next`は接続されて
    // いない(Python版の既知の制約、このRust版でもそのまま踏襲)。
    let items: Vec<String> = sqlx::query_scalar(
        r#"
        SELECT a.ap_id
        FROM actors a
        JOIN followers f ON f.follower_id = a.id
        WHERE f.following_id = $1 AND f.accepted = true
        ORDER BY f.created_at DESC
        LIMIT 40
        "#,
    )
    .bind(actor_id)
    .fetch_all(&state.db)
    .await?;
    let body = render_ordered_collection_page(
        &format!("{collection_url}?page=true"),
        &collection_url,
        items,
    );
    Ok(ap_json_response(StatusCode::OK, &body))
}

/// `app/activitypub/routes.py` の `get_following_collection` を移植したもの。
/// `get_followers_collection`と対称(follower_id/following_idを入れ替えるのみ)。
async fn get_following_collection(
    State(state): State<AppState>,
    Path(username): Path<String>,
    Query(query): Query<PageQuery>,
) -> Result<Response, AppError> {
    let actor_id = fetch_local_actor_id(&state.db, &username).await?;
    let collection_url = format!("{}/users/{username}/following", state.config.server_url());

    if !query.page {
        let total: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM followers WHERE follower_id = $1 AND accepted = true",
        )
        .bind(actor_id)
        .fetch_one(&state.db)
        .await?;
        let body = render_ordered_collection(
            &collection_url,
            total,
            &format!("{collection_url}?page=true"),
        );
        return Ok(ap_json_response(StatusCode::OK, &body));
    }

    let items: Vec<String> = sqlx::query_scalar(
        r#"
        SELECT a.ap_id
        FROM actors a
        JOIN followers f ON f.following_id = a.id
        WHERE f.follower_id = $1 AND f.accepted = true
        ORDER BY f.created_at DESC
        LIMIT 40
        "#,
    )
    .bind(actor_id)
    .fetch_all(&state.db)
    .await?;
    let body = render_ordered_collection_page(
        &format!("{collection_url}?page=true"),
        &collection_url,
        items,
    );
    Ok(ap_json_response(StatusCode::OK, &body))
}
