//! `app/activitypub/routes.py` の `get_actor`/`get_followers_collection`/
//! `get_following_collection`/`get_outbox`/`get_featured` を移植したもの。
//! `get_actor_by_username(db, username, domain=None)` はローカルアクターしか
//! 返さないため、`render_actor`のリモートアクター分岐(保存済みURL列を
//! そのまま使う側)は不要 — これらのエンドポイントに関する限りアクターは
//! 常にローカルである。同じ理由で `get_outbox`/`get_featured` がレンダリング
//! するノートの著者(`note.actor`)も常にこのルートのローカルactorに固定
//! されるため、ノートごとに actor を引き直す必要がない。

use std::collections::HashMap;

use axum::extract::{Path, Query, State};
use axum::http::{header, HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use axum::Router;
use chrono::{DateTime, NaiveDate, Utc};
use serde::Deserialize;
use serde_json::{json, Value};
use sqlx::PgPool;
use uuid::Uuid;

use crate::activitypub::{
    iso_z, render_create_activity, render_note, render_ordered_collection,
    render_ordered_collection_page, resolve_source_media_type, truthy_string, NoteAttachmentData,
    NoteRenderData, AP_CONTEXT,
};
use crate::error::AppError;
use crate::note_visibility::is_visible_to_anonymous;
use crate::state::AppState;

const AP_CONTENT_TYPE: &str = "application/activity+json; charset=utf-8";

/// outbox 1ページあたりの件数。`app/activitypub/routes.py` の `get_outbox` と同一。
const OUTBOX_PAGE_SIZE: i64 = 20;

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/users/:username", get(get_actor))
        .route("/users/:username/outbox", get(get_outbox))
        .route("/users/:username/followers", get(get_followers_collection))
        .route("/users/:username/following", get(get_following_collection))
        .route("/users/:username/featured", get(get_featured))
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

/// `app/services/note_service.py` の `_note_load_options` 相当だが、
/// `render_note` が実際に読む列だけに絞ってある(`quoted_note`/`renote_of`
/// リレーションは `render_note` が参照しないため取得しない)。
/// `get_outbox`/`get_featured` はどちらもこの行から `NoteRenderData` を組み立てる。
#[derive(sqlx::FromRow)]
struct NoteRow {
    id: Uuid,
    ap_id: String,
    visibility: String,
    is_poll: bool,
    content: String,
    published: DateTime<Utc>,
    #[sqlx(rename = "to")]
    to_field: Value,
    cc: Value,
    updated_at: Option<DateTime<Utc>>,
    source: Option<String>,
    sensitive: bool,
    spoiler_text: Option<String>,
    in_reply_to_ap_id: Option<String>,
    quote_ap_id: Option<String>,
    mentions: Option<Value>,
    is_talk: bool,
    poll_options: Option<Value>,
    poll_expires_at: Option<DateTime<Utc>>,
    poll_multiple: bool,
}

/// `app/activitypub/renderer.py` の `render_note` が添付ファイルに使う列。
/// `att.drive_file`(存在すれば`df_s3_key`が埋まる)/`att.remote_url` の
/// 2系統をそのまま反映できるよう、加工前の生列で取得する。
#[derive(sqlx::FromRow)]
struct AttachmentRow {
    note_id: Uuid,
    remote_url: Option<String>,
    remote_mime_type: Option<String>,
    remote_name: Option<String>,
    remote_description: Option<String>,
    df_mime_type: Option<String>,
    df_description: Option<String>,
    df_filename: Option<String>,
    df_width: Option<i32>,
    df_height: Option<i32>,
    df_blurhash: Option<String>,
    df_focal_x: Option<f64>,
    df_focal_y: Option<f64>,
    df_s3_key: Option<String>,
    df_thumbnail_s3_key: Option<String>,
    df_thumbnail_mime_type: Option<String>,
    df_duration: Option<f64>,
}

/// `app/activitypub/renderer.py` の `render_note` 内、`note.attachments` ループを
/// 移植したもの。ノートIDごとに `NoteAttachmentData` へ変換して返す。
/// `create_status`(添付ファイルをAP Create配送用にレンダリングする際)からも
/// 再利用するため `pub`。
pub async fn fetch_attachments_by_note(
    db: &PgPool,
    note_ids: &[Uuid],
    media_url: &str,
) -> Result<HashMap<Uuid, Vec<NoteAttachmentData>>, AppError> {
    let mut map: HashMap<Uuid, Vec<NoteAttachmentData>> = HashMap::new();
    if note_ids.is_empty() {
        return Ok(map);
    }

    let rows = sqlx::query_as::<_, AttachmentRow>(
        r#"
        SELECT na.note_id,
               na.remote_url, na.remote_mime_type, na.remote_name, na.remote_description,
               df.mime_type AS df_mime_type, df.description AS df_description,
               df.filename AS df_filename, df.width AS df_width, df.height AS df_height,
               df.blurhash AS df_blurhash, df.focal_x AS df_focal_x, df.focal_y AS df_focal_y,
               df.s3_key AS df_s3_key, df.thumbnail_s3_key AS df_thumbnail_s3_key,
               df.thumbnail_mime_type AS df_thumbnail_mime_type, df.duration AS df_duration
        FROM note_attachments na
        LEFT JOIN drive_files df ON df.id = na.drive_file_id
        WHERE na.note_id = ANY($1)
        ORDER BY na.note_id, na.position
        "#,
    )
    .bind(note_ids)
    .fetch_all(db)
    .await?;

    for row in rows {
        // `if att.drive_file:` 相当 — LEFT JOIN が実際にマッチしたか
        // (`s3_key` は drive_files の NOT NULL 列なので存在確認に使える)。
        let attachment = if let Some(s3_key) = row.df_s3_key {
            let icon = truthy_string(row.df_thumbnail_s3_key).map(|key| {
                let icon_media_type = truthy_string(row.df_thumbnail_mime_type)
                    .unwrap_or_else(|| "image/webp".into());
                (icon_media_type, format!("{media_url}/{key}"))
            });
            Some(NoteAttachmentData {
                media_type: row.df_mime_type.unwrap_or_default(),
                url: format!("{media_url}/{s3_key}"),
                name: truthy_string(row.df_description)
                    .or_else(|| truthy_string(row.df_filename))
                    .unwrap_or_default(),
                width: row.df_width,
                height: row.df_height,
                blurhash: truthy_string(row.df_blurhash),
                focal_point: match (row.df_focal_x, row.df_focal_y) {
                    (Some(x), Some(y)) => Some([x, y]),
                    _ => None,
                },
                icon,
                duration: row.df_duration,
            })
        } else if let Some(remote_url) = truthy_string(row.remote_url) {
            Some(NoteAttachmentData {
                media_type: truthy_string(row.remote_mime_type)
                    .unwrap_or_else(|| "application/octet-stream".into()),
                url: remote_url,
                name: truthy_string(row.remote_description)
                    .or_else(|| truthy_string(row.remote_name))
                    .unwrap_or_default(),
                ..Default::default()
            })
        } else {
            None
        };

        if let Some(attachment) = attachment {
            map.entry(row.note_id).or_default().push(attachment);
        }
    }

    Ok(map)
}

/// `NoteRow` のリストを、`render_note`/`render_create_activity` にそのまま
/// 渡せる `NoteRenderData` のリストへ組み立てる。`get_outbox`/`get_featured`
/// の両方から使う共通処理(actor/preferences/attachmentsの解決)。
async fn build_note_render_data(
    db: &PgPool,
    server_url: &str,
    media_url: &str,
    actor_id: Uuid,
    actor_ap_id: &str,
    notes: Vec<NoteRow>,
) -> Result<Vec<NoteRenderData>, AppError> {
    if notes.is_empty() {
        return Ok(Vec::new());
    }

    // `note.actor.local_user.preferences` 相当。このルートのノートは全て
    // 同一のローカルactorに属するため、リクエストにつき1回だけ引けば足りる。
    let preferences: Option<Value> =
        sqlx::query_scalar("SELECT preferences FROM users WHERE actor_id = $1")
            .bind(actor_id)
            .fetch_optional(db)
            .await?
            .flatten();

    let note_ids: Vec<Uuid> = notes.iter().map(|n| n.id).collect();
    let mut attachments = fetch_attachments_by_note(db, &note_ids, media_url).await?;

    let render_data = notes
        .into_iter()
        .map(|n| {
            let note_url = format!("{server_url}/notes/{}", n.id);
            let source_media_type = n
                .source
                .as_deref()
                .filter(|s| !s.is_empty())
                .map(|s| resolve_source_media_type(s, preferences.as_ref()).to_string());
            NoteRenderData {
                ap_id: n.ap_id,
                is_poll: n.is_poll,
                attributed_to: actor_ap_id.to_string(),
                content: n.content,
                published: n.published,
                to: n.to_field,
                cc: n.cc,
                note_url,
                updated_at: n.updated_at,
                source: n.source,
                source_media_type,
                sensitive: n.sensitive,
                spoiler_text: n.spoiler_text,
                in_reply_to_ap_id: n.in_reply_to_ap_id,
                quote_ap_id: n.quote_ap_id,
                mentions: n.mentions,
                attachments: attachments.remove(&n.id).unwrap_or_default(),
                poll_options: n.poll_options,
                poll_expires_at: n.poll_expires_at,
                poll_multiple: n.poll_multiple,
                is_talk: n.is_talk,
                hashtags: Vec::new(),
                emoji_tags: Vec::new(),
            }
        })
        .collect();
    Ok(render_data)
}

/// `app/activitypub/routes.py` の `get_outbox` を移植したもの。
async fn get_outbox(
    State(state): State<AppState>,
    Path(username): Path<String>,
    Query(query): Query<PageQuery>,
) -> Result<Response, AppError> {
    let actor_id = fetch_local_actor_id(&state.db, &username).await?;
    let server_url = state.config.server_url();
    let outbox_url = format!("{server_url}/users/{username}/outbox");

    if !query.page {
        let total: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM notes \
             WHERE actor_id = $1 AND local = true AND visibility = 'public' AND deleted_at IS NULL",
        )
        .bind(actor_id)
        .fetch_one(&state.db)
        .await?;
        let body =
            render_ordered_collection(&outbox_url, total, &format!("{outbox_url}?page=true"));
        return Ok(ap_json_response(StatusCode::OK, &body));
    }

    let notes = sqlx::query_as::<_, NoteRow>(
        r#"
        SELECT id, ap_id, visibility, is_poll, content, published, "to", cc, updated_at,
               source, sensitive, spoiler_text, in_reply_to_ap_id, quote_ap_id, mentions,
               is_talk, poll_options, poll_expires_at, poll_multiple
        FROM notes
        WHERE actor_id = $1 AND local = true AND visibility = 'public' AND deleted_at IS NULL
        ORDER BY published DESC
        LIMIT $2
        "#,
    )
    .bind(actor_id)
    .bind(OUTBOX_PAGE_SIZE)
    .fetch_all(&state.db)
    .await?;

    let actor_ap_id = format!("{server_url}/users/{username}");
    let media_url = state.config.media_url();
    let render_data = build_note_render_data(
        &state.db,
        &server_url,
        &media_url,
        actor_id,
        &actor_ap_id,
        notes,
    )
    .await?;
    let items: Vec<Value> = render_data.iter().map(render_create_activity).collect();

    let body =
        render_ordered_collection_page(&format!("{outbox_url}?page=true"), &outbox_url, items);
    Ok(ap_json_response(StatusCode::OK, &body))
}

/// `get_featured` が可視性判定に必要とするローカルactorの最小限の列。
#[derive(sqlx::FromRow)]
struct FeaturedActorRow {
    id: Uuid,
    make_notes_hidden_before: Option<i64>,
    make_notes_followers_only_before: Option<i64>,
}

/// `app/activitypub/routes.py` の `get_featured` を移植したもの。
/// Python版は常に未認証閲覧者向け(`filter_visible_notes(db, notes, None)`)
/// なので `is_visible_to_anonymous` で判定する。
async fn get_featured(
    State(state): State<AppState>,
    Path(username): Path<String>,
) -> Result<Response, AppError> {
    let actor = sqlx::query_as::<_, FeaturedActorRow>(
        "SELECT id, make_notes_hidden_before, make_notes_followers_only_before \
         FROM actors WHERE username = $1 AND domain IS NULL",
    )
    .bind(username.to_lowercase())
    .fetch_optional(&state.db)
    .await?
    .ok_or_else(|| AppError::not_found("Actor not found"))?;

    let pinned_notes = sqlx::query_as::<_, NoteRow>(
        r#"
        SELECT n.id, n.ap_id, n.visibility, n.is_poll, n.content, n.published, n."to", n.cc,
               n.updated_at, n.source, n.sensitive, n.spoiler_text, n.in_reply_to_ap_id,
               n.quote_ap_id, n.mentions, n.is_talk, n.poll_options, n.poll_expires_at,
               n.poll_multiple
        FROM pinned_notes pn
        JOIN notes n ON n.id = pn.note_id
        WHERE pn.actor_id = $1 AND n.deleted_at IS NULL
        ORDER BY pn.position
        "#,
    )
    .bind(actor.id)
    .fetch_all(&state.db)
    .await?;

    let visible_notes: Vec<NoteRow> = pinned_notes
        .into_iter()
        .filter(|n| {
            is_visible_to_anonymous(
                &n.visibility,
                n.published,
                actor.make_notes_hidden_before,
                actor.make_notes_followers_only_before,
            )
        })
        .collect();

    let server_url = state.config.server_url();
    let media_url = state.config.media_url();
    let actor_ap_id = format!("{server_url}/users/{username}");
    let render_data = build_note_render_data(
        &state.db,
        &server_url,
        &media_url,
        actor.id,
        &actor_ap_id,
        visible_notes,
    )
    .await?;
    let items: Vec<Value> = render_data.iter().map(render_note).collect();

    let featured_url = format!("{server_url}/users/{username}/featured");
    let body = json!({
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": featured_url,
        "type": "OrderedCollection",
        "totalItems": items.len(),
        "orderedItems": items,
    });
    Ok(ap_json_response(StatusCode::OK, &body))
}
