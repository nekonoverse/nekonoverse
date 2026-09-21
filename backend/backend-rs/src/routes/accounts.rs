//! `app/api/mastodon/accounts.py` のうち、リモート WebFinger 解決を必要としない
//! 純粋な読み取り専用エンドポイント (`list_followers`/`list_following`/
//! `get_relationship`/`get_relationships_batch`) を移植したもの。
//!
//! `lookup_account`/`search_accounts` はローカルに存在しないリモート acct を
//! `resolve_webfinger` (署名付きHTTPフェッチ + アクター取り込み) で解決する
//! 経路を持ち、これは media-proxy/inbox 以来の新たな対外通信能力を要する
//! 大きな一枚岩のため、過剰にコミットしないという Stage 4 の方針
//! (#1139) に従い別PRへ送る。`get_account`/`get_accounts_batch` も
//! `get_follow_counts`/`get_statuses_count` の Valkey キャッシュ込みの
//! 移植が必要でこの単純な読み取り専用スライスの範囲を超えるため見送る。

use std::collections::{HashMap, HashSet};

use axum::extract::{Path, Query, RawQuery, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use axum::{Json, Router};
use chrono::{DateTime, Utc};
use serde::Deserialize;
use serde_json::{json, Value};
use sqlx::PgPool;
use url::form_urlencoded;
use uuid::Uuid;

use crate::auth::{CurrentUser, OptionalUser};
use crate::config::Config;
use crate::error::AppError;
use crate::hmac_sig::media_proxy_url;
use crate::mastodon_time::to_mastodon_datetime;
use crate::state::AppState;

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/api/v1/accounts/:actor_id/followers", get(list_followers))
        .route("/api/v1/accounts/:actor_id/following", get(list_following))
        .route(
            "/api/v1/accounts/:actor_id/relationship",
            get(get_relationship),
        )
        .route(
            "/api/v1/accounts/relationships",
            get(get_relationships_batch),
        )
}

/// `_actor_to_account`/`_batch_resolve_actor_emojis` が読む Actor の列一式。
#[derive(sqlx::FromRow)]
struct AccountActorRow {
    id: Uuid,
    username: String,
    domain: Option<String>,
    display_name: Option<String>,
    summary: Option<String>,
    ap_id: String,
    avatar_url: Option<String>,
    header_url: Option<String>,
    created_at: DateTime<Utc>,
    is_bot: bool,
    #[sqlx(rename = "type")]
    actor_type: String,
    manually_approves_followers: bool,
    discoverable: bool,
    fields: Option<Value>,
    moved_to_ap_id: Option<String>,
}

const ACCOUNT_ACTOR_COLUMNS: &str = "id, username, domain, display_name, summary, ap_id, \
    avatar_url, header_url, created_at, is_bot, type, manually_approves_followers, \
    discoverable, fields, moved_to_ap_id";

/// `ACCOUNT_ACTOR_COLUMNS` の各列を `actors` のエイリアス `a` で修飾したもの。
/// `followers` と JOIN するクエリで列名の曖昧さを避けるために使う。
const ACCOUNT_ACTOR_COLUMNS_ALIASED: &str = "a.id, a.username, a.domain, a.display_name, \
    a.summary, a.ap_id, a.avatar_url, a.header_url, a.created_at, a.is_bot, a.type, \
    a.manually_approves_followers, a.discoverable, a.fields, a.moved_to_ap_id";

async fn fetch_account_row_by_ap_id(
    db: &PgPool,
    ap_id: &str,
) -> Result<Option<AccountActorRow>, AppError> {
    let query = format!("SELECT {ACCOUNT_ACTOR_COLUMNS} FROM actors WHERE ap_id = $1");
    let row = sqlx::query_as::<_, AccountActorRow>(&query)
        .bind(ap_id)
        .fetch_optional(db)
        .await?;
    Ok(row)
}

/// `app/api/mastodon/accounts.py` の `_actor_to_account` を移植したもの。
/// followers_count/following_count/statuses_count/last_status_at は、
/// このPRで移植する呼び出し元(`list_followers`/`list_following`)がいずれも
/// カウントを渡さない (Python版の `_actor_to_account(a, db=db, resolve_emojis=False)`
/// 呼び出しと同じ、常に0/nullになる) 挙動をそのまま踏襲する。カウント込みの
/// 版が要る `get_account`/`lookup_account`/`search_accounts` は別PR。
fn account_json_base(config: &Config, row: &AccountActorRow, emojis: Vec<Value>) -> Value {
    let avatar_proxy = media_proxy_url(config, row.avatar_url.as_deref(), Some("avatar"), false);
    let avatar = if avatar_proxy.is_empty() {
        format!("{}/default-avatar.svg", config.server_url())
    } else {
        avatar_proxy
    };
    let avatar_static_proxy =
        media_proxy_url(config, row.avatar_url.as_deref(), Some("avatar"), true);
    let avatar_static = if avatar_static_proxy.is_empty() {
        avatar.clone()
    } else {
        avatar_static_proxy
    };
    let header = media_proxy_url(config, row.header_url.as_deref(), None, false);

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

    json!({
        "id": row.id.to_string(),
        "username": row.username,
        "acct": match &row.domain {
            Some(domain) => format!("{}@{domain}", row.username),
            None => row.username.clone(),
        },
        "display_name": row.display_name.clone().unwrap_or_default(),
        "note": row.summary.clone().unwrap_or_default(),
        "uri": row.ap_id,
        "avatar": avatar,
        "avatar_static": avatar_static,
        "header": header,
        "header_static": header,
        "url": row.ap_id,
        "created_at": to_mastodon_datetime(row.created_at),
        "bot": row.is_bot || row.actor_type == "Service",
        "group": row.actor_type == "Group",
        "locked": row.manually_approves_followers,
        "discoverable": row.discoverable,
        "fields": fields,
        "emojis": emojis,
        "followers_count": 0,
        "following_count": 0,
        "statuses_count": 0,
        "last_status_at": Value::Null,
    })
}

/// `account_json_base` に `moved` フィールドの解決(実際の移行先アカウントの
/// 引き直し)を追加したもの。Python版と同じく `moved` の中身にはカウントも
/// 絵文字も付かない(再帰1段限り、`db=None` 相当)。
async fn build_account_json(
    db: &PgPool,
    config: &Config,
    row: &AccountActorRow,
    emojis: Vec<Value>,
) -> Result<Value, AppError> {
    let mut data = account_json_base(config, row, emojis);
    if let Some(moved_ap_id) = &row.moved_to_ap_id {
        if let Some(moved_row) = fetch_account_row_by_ap_id(db, moved_ap_id).await? {
            data["moved"] = account_json_base(config, &moved_row, Vec::new());
        }
    }
    Ok(data)
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

/// `:([a-zA-Z0-9_]+):` の非重複マッチを Python の `re.findall` と同じ規則
/// (貪欲・前の一致の直後から再走査)で抽出する。正規表現クレートを増やす
/// ほどの複雑さではないため手書きする。
fn find_shortcodes(text: &str, out: &mut HashSet<String>) {
    let bytes = text.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b':' {
            let start = i + 1;
            let mut j = start;
            while j < bytes.len() && (bytes[j].is_ascii_alphanumeric() || bytes[j] == b'_') {
                j += 1;
            }
            if j > start && j < bytes.len() && bytes[j] == b':' {
                out.insert(text[start..j].to_string());
                i = j + 1;
                continue;
            }
        }
        i += 1;
    }
}

fn collect_actor_shortcodes(actor: &AccountActorRow) -> HashSet<String> {
    let mut codes = HashSet::new();
    find_shortcodes(actor.display_name.as_deref().unwrap_or(""), &mut codes);
    find_shortcodes(actor.summary.as_deref().unwrap_or(""), &mut codes);
    if let Some(fields) = actor.fields.as_ref().and_then(|v| v.as_array()) {
        for f in fields {
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
    codes
}

/// `app/api/mastodon/accounts.py` の `_batch_resolve_actor_emojis` を
/// 移植したもの。複数アクターのカスタム絵文字を最大2クエリでバッチ解決する。
async fn batch_resolve_actor_emojis(
    db: &PgPool,
    config: &Config,
    actors: &[AccountActorRow],
) -> Result<HashMap<Uuid, Vec<Value>>, AppError> {
    let mut actor_shortcodes: HashMap<Uuid, HashSet<String>> = HashMap::new();
    let mut all_shortcodes: HashSet<String> = HashSet::new();
    for actor in actors {
        let codes = collect_actor_shortcodes(actor);
        all_shortcodes.extend(codes.iter().cloned());
        actor_shortcodes.insert(actor.id, codes);
    }

    if all_shortcodes.is_empty() {
        return Ok(HashMap::new());
    }

    let all_codes: Vec<String> = all_shortcodes.iter().cloned().collect();
    let local_rows: Vec<EmojiRow> = sqlx::query_as(
        "SELECT shortcode, url, static_url FROM custom_emojis \
         WHERE shortcode = ANY($1) AND domain IS NULL",
    )
    .bind(&all_codes)
    .fetch_all(db)
    .await?;
    let local_map: HashMap<String, EmojiRow> = local_rows
        .into_iter()
        .map(|e| (e.shortcode.clone(), e))
        .collect();

    let missing: Vec<String> = all_shortcodes
        .iter()
        .filter(|s| !local_map.contains_key(*s))
        .cloned()
        .collect();
    let mut remote_map: HashMap<String, EmojiRow> = HashMap::new();
    if !missing.is_empty() {
        let remote_rows: Vec<EmojiRow> = sqlx::query_as(
            "SELECT shortcode, url, static_url FROM custom_emojis \
             WHERE shortcode = ANY($1) AND domain IS NOT NULL",
        )
        .bind(&missing)
        .fetch_all(db)
        .await?;
        for e in remote_rows {
            remote_map.entry(e.shortcode.clone()).or_insert(e);
        }
    }

    let mut emoji_map: HashMap<Uuid, Vec<Value>> = HashMap::new();
    for actor in actors {
        let codes = actor_shortcodes.get(&actor.id);
        let Some(codes) = codes else { continue };
        if codes.is_empty() {
            continue;
        }
        let mut emojis = Vec::new();
        for code in codes {
            if let Some(e) = local_map.get(code).or_else(|| remote_map.get(code)) {
                emojis.push(emoji_json(config, e));
            }
        }
        if !emojis.is_empty() {
            emoji_map.insert(actor.id, emojis);
        }
    }
    Ok(emoji_map)
}

#[derive(Deserialize)]
struct LimitQuery {
    limit: Option<i64>,
}

/// `Query(default, ge=1)` (FastAPI) の下限検証を移植したもの。
fn validated_limit(raw: Option<i64>, default: i64, max: i64) -> Result<i64, AppError> {
    match raw {
        None => Ok(default),
        Some(l) if l < 1 => Err(AppError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "limit must be greater than or equal to 1",
        )),
        Some(l) => Ok(l.min(max)),
    }
}

async fn fetch_require_signin_to_view(
    db: &PgPool,
    actor_id: Uuid,
) -> Result<Option<bool>, AppError> {
    let row: Option<(bool,)> =
        sqlx::query_as("SELECT require_signin_to_view FROM actors WHERE id = $1")
            .bind(actor_id)
            .fetch_optional(db)
            .await?;
    Ok(row.map(|(v,)| v))
}

async fn render_accounts(
    db: &PgPool,
    config: &Config,
    rows: Vec<AccountActorRow>,
) -> Result<Vec<Value>, AppError> {
    let emoji_map = batch_resolve_actor_emojis(db, config, &rows).await?;
    let mut accounts = Vec::with_capacity(rows.len());
    for row in &rows {
        let emojis = emoji_map.get(&row.id).cloned().unwrap_or_default();
        accounts.push(build_account_json(db, config, row, emojis).await?);
    }
    Ok(accounts)
}

/// `app/api/mastodon/accounts.py` の `list_followers` を移植したもの。
async fn list_followers(
    State(state): State<AppState>,
    Path(actor_id): Path<Uuid>,
    Query(query): Query<LimitQuery>,
    OptionalUser(user): OptionalUser,
) -> Result<Response, AppError> {
    let require_signin = fetch_require_signin_to_view(&state.db, actor_id)
        .await?
        .ok_or_else(|| AppError::not_found("Actor not found"))?;
    if require_signin && user.is_none() {
        return Ok(Json(Vec::<Value>::new()).into_response());
    }

    let limit = validated_limit(query.limit, 40, 80)?;
    let query_sql = format!(
        "SELECT {ACCOUNT_ACTOR_COLUMNS_ALIASED} FROM actors a \
         JOIN followers f ON f.follower_id = a.id \
         WHERE f.following_id = $1 AND f.accepted = true \
         ORDER BY f.created_at DESC LIMIT $2",
    );
    let rows = sqlx::query_as::<_, AccountActorRow>(&query_sql)
        .bind(actor_id)
        .bind(limit)
        .fetch_all(&state.db)
        .await?;

    let accounts = render_accounts(&state.db, &state.config, rows).await?;
    Ok(Json(accounts).into_response())
}

/// `app/api/mastodon/accounts.py` の `list_following` を移植したもの。
/// `list_followers` と対称(follower_id/following_idを入れ替えるのみ)。
async fn list_following(
    State(state): State<AppState>,
    Path(actor_id): Path<Uuid>,
    Query(query): Query<LimitQuery>,
    OptionalUser(user): OptionalUser,
) -> Result<Response, AppError> {
    let require_signin = fetch_require_signin_to_view(&state.db, actor_id)
        .await?
        .ok_or_else(|| AppError::not_found("Actor not found"))?;
    if require_signin && user.is_none() {
        return Ok(Json(Vec::<Value>::new()).into_response());
    }

    let limit = validated_limit(query.limit, 40, 80)?;
    let query_sql = format!(
        "SELECT {ACCOUNT_ACTOR_COLUMNS_ALIASED} FROM actors a \
         JOIN followers f ON f.following_id = a.id \
         WHERE f.follower_id = $1 AND f.accepted = true \
         ORDER BY f.created_at DESC LIMIT $2",
    );
    let rows = sqlx::query_as::<_, AccountActorRow>(&query_sql)
        .bind(actor_id)
        .bind(limit)
        .fetch_all(&state.db)
        .await?;

    let accounts = render_accounts(&state.db, &state.config, rows).await?;
    Ok(Json(accounts).into_response())
}

fn relationship_json(
    actor_id: Uuid,
    following: bool,
    followed_by: bool,
    blocking: bool,
    muting: bool,
    requested: bool,
) -> Value {
    json!({
        "id": actor_id.to_string(),
        "following": following,
        "followed_by": followed_by,
        "blocking": blocking,
        "muting": muting,
        "requested": requested,
        "showing_reblogs": true,
        "notifying": false,
        "domain_blocking": false,
        "endorsed": false,
        "muting_notifications": false,
        "note": "",
        "languages": Value::Null,
    })
}

/// `app/api/mastodon/accounts.py` の `get_relationship` を移植したもの。
async fn get_relationship(
    State(state): State<AppState>,
    current_user: CurrentUser,
    Path(actor_id): Path<Uuid>,
) -> Result<Response, AppError> {
    let follow_rows: Vec<(Uuid, bool)> = sqlx::query_as(
        "SELECT follower_id, accepted FROM followers \
         WHERE (follower_id = $1 AND following_id = $2) \
            OR (follower_id = $2 AND following_id = $1)",
    )
    .bind(current_user.actor_id)
    .bind(actor_id)
    .fetch_all(&state.db)
    .await?;

    let mut following = false;
    let mut followed_by = false;
    let mut requested = false;
    for (follower_id, accepted) in follow_rows {
        if follower_id == current_user.actor_id {
            following = accepted;
            requested = !accepted;
        } else if accepted {
            followed_by = true;
        }
    }

    let blocking: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM user_blocks WHERE actor_id = $1 AND target_id = $2)",
    )
    .bind(current_user.actor_id)
    .bind(actor_id)
    .fetch_one(&state.db)
    .await?;

    let now = Utc::now();
    let muting: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM user_mutes WHERE actor_id = $1 AND target_id = $2 \
         AND (expires_at IS NULL OR expires_at > $3))",
    )
    .bind(current_user.actor_id)
    .bind(actor_id)
    .bind(now)
    .fetch_one(&state.db)
    .await?;

    Ok(Json(relationship_json(
        actor_id,
        following,
        followed_by,
        blocking,
        muting,
        requested,
    ))
    .into_response())
}

/// `id[]=...&id[]=...` の繰り返しクエリパラメータを取り出す。axum の
/// `Query` 抽出器 (serde_urlencoded) は同名キーの繰り返しを `Vec` へ集約
/// できないため、生のクエリ文字列を直接パースする
/// (`app/api/mastodon/accounts.py` の `Query(alias="id[]")` に相当)。
fn parse_repeated_query_param(raw_query: Option<&str>, key: &str) -> Vec<String> {
    let Some(raw) = raw_query else {
        return Vec::new();
    };
    form_urlencoded::parse(raw.as_bytes())
        .filter(|(k, _)| k == key)
        .map(|(_, v)| v.into_owned())
        .collect()
}

/// `app/api/mastodon/accounts.py` の `get_relationships_batch` を移植したもの。
async fn get_relationships_batch(
    State(state): State<AppState>,
    current_user: CurrentUser,
    RawQuery(raw_query): RawQuery,
) -> Result<Response, AppError> {
    let ids = parse_repeated_query_param(raw_query.as_deref(), "id[]");
    if ids.is_empty() {
        return Ok(Json(Vec::<Value>::new()).into_response());
    }

    // 悪用防止のため40件に制限、無効なUUIDは無視 (Python版と同じ)。
    let actor_ids: Vec<Uuid> = ids
        .iter()
        .take(40)
        .filter_map(|raw| Uuid::parse_str(raw).ok())
        .collect();
    if actor_ids.is_empty() {
        return Ok(Json(Vec::<Value>::new()).into_response());
    }

    let outgoing: Vec<(Uuid, bool)> = sqlx::query_as(
        "SELECT following_id, accepted FROM followers \
         WHERE follower_id = $1 AND following_id = ANY($2)",
    )
    .bind(current_user.actor_id)
    .bind(&actor_ids)
    .fetch_all(&state.db)
    .await?;
    let outgoing_map: HashMap<Uuid, bool> = outgoing.into_iter().collect();

    let followed_by_ids: HashSet<Uuid> = sqlx::query_scalar(
        "SELECT follower_id FROM followers \
         WHERE follower_id = ANY($1) AND following_id = $2 AND accepted = true",
    )
    .bind(&actor_ids)
    .bind(current_user.actor_id)
    .fetch_all(&state.db)
    .await?
    .into_iter()
    .collect();

    let blocked_ids: HashSet<Uuid> =
        sqlx::query_scalar("SELECT target_id FROM user_blocks WHERE actor_id = $1")
            .bind(current_user.actor_id)
            .fetch_all(&state.db)
            .await?
            .into_iter()
            .collect();

    let now = Utc::now();
    let muted_ids: HashSet<Uuid> = sqlx::query_scalar(
        "SELECT target_id FROM user_mutes WHERE actor_id = $1 \
         AND (expires_at IS NULL OR expires_at > $2)",
    )
    .bind(current_user.actor_id)
    .bind(now)
    .fetch_all(&state.db)
    .await?
    .into_iter()
    .collect();

    let results: Vec<Value> = actor_ids
        .iter()
        .map(|aid| {
            let accepted = outgoing_map.get(aid).copied();
            let following = accepted.unwrap_or(false);
            let requested = accepted.map(|a| !a).unwrap_or(false);
            relationship_json(
                *aid,
                following,
                followed_by_ids.contains(aid),
                blocked_ids.contains(aid),
                muted_ids.contains(aid),
                requested,
            )
        })
        .collect();

    Ok(Json(results).into_response())
}
