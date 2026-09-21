//! `app/api/mastodon/statuses.py` の `note_to_response`(Note→Mastodon互換
//! JSON 変換)を構成するヘルパー群を移植したもの。Issue #1139 Stage 4の
//! 「NoteResponse直列化パイプライン」着手の第一弾。
//!
//! **このモジュールはまだどの axum ルートにも配線しない。** `note_to_response`
//! 自体は `reblog`/`quote` の解決を関数内部の先頭で行う(`renote_of`/
//! `quoted_note` を辿って再帰的に自分自身を呼ぶ)が、この再帰と実際の
//! `GET /api/v1/statuses/{id}` ルート配線は次のPRに送る。ここでは
//! reblog/quote が既に解決済み(呼び出し側が `Option<Value>` として渡す)
//! という前提の「末端」変換ロジック本体 — 添付ファイル・カスタム絵文字・
//! ハッシュタグ・リアクション集計・投票・返信先メンション・プレビュー
//! カード・アクター描画 — だけを切り出して先に固める。理由:
//! `note_to_response` は柔軟な巨大関数で、`get_note_by_id` (FKが未解決な
//! 場合は `fetch_remote_note` による署名付きHTTP遅延フェッチへフォール
//! バックする)を経由した無制限の再帰を許すため、再帰境界の設計だけでも
//! 独立した検討が要る。過剰にコミットしないという Stage 4 の方針
//! (#1139) に従い、まず再帰非依存の部分を確定させる。
//!
//! punt した(未移植の)Python側の分岐:
//! - `note.renote_of_ap_id`/`note.quote_ap_id` のみ設定されFK(`_id`)が
//!   未解決な場合の `fetch_remote_note` 遅延フェッチ(署名付きHTTPで
//!   未知のリモートノートを取り込む)。`resolve_webfinger`/
//!   `fetch_remote_actor` と同種の新たな対外通信能力が要るため。
//! - `get_domain_software_info` の Valkey キャッシュミス時の生フェッチ
//!   (`_fetch_software`)。キャッシュヒットのみ読み、ミス時は
//!   `(None, None, None)` を返す(Python側の他エンドポイントが同じ
//!   Valkeyキーを埋めるため自己修復的)。

use std::collections::{HashMap, HashSet};

use chrono::{DateTime, Utc};
use redis::AsyncCommands;
use serde_json::{json, Value};
use sqlx::PgPool;
use uuid::Uuid;

use crate::config::Config;
use crate::error::AppError;
use crate::hmac_sig::media_proxy_url;
use crate::mastodon_time::to_mastodon_datetime;
use crate::shortcode::find_shortcodes;

/// `note_to_response` の呼び出し元が持つべき Note + 著者Actor の結合行。
/// `app/services/note_service.py` の `get_note_by_id`(`_note_load_options`)
/// が返す `Note`/`Note.actor` のうち、この末端変換に必要な列のみ。
#[derive(sqlx::FromRow)]
pub struct NoteRenderRow {
    pub id: Uuid,
    pub ap_id: String,
    pub content: String,
    pub source: Option<String>,
    pub visibility: String,
    pub sensitive: bool,
    pub spoiler_text: Option<String>,
    pub published: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
    pub replies_count: i32,
    pub reactions_count: i32,
    pub renotes_count: i32,
    pub in_reply_to_id: Option<Uuid>,
    pub is_poll: bool,
    pub poll_options: Option<Value>,
    pub poll_expires_at: Option<DateTime<Utc>>,
    pub poll_multiple: bool,
    pub local: bool,
    pub actor_id: Uuid,
    pub actor_username: String,
    pub actor_display_name: Option<String>,
    pub actor_avatar_url: Option<String>,
    pub actor_header_url: Option<String>,
    pub actor_ap_id: String,
    pub actor_domain: Option<String>,
    pub actor_is_cat: bool,
    pub actor_is_bot: bool,
    pub actor_type: String,
    pub actor_manually_approves_followers: bool,
    pub actor_discoverable: bool,
    pub actor_summary: Option<String>,
    pub actor_created_at: DateTime<Utc>,
}

const NOTE_RENDER_COLUMNS: &str = "n.id, n.ap_id, n.content, n.source, n.visibility, n.sensitive, \
    n.spoiler_text, n.published, n.updated_at, n.replies_count, n.reactions_count, \
    n.renotes_count, n.in_reply_to_id, n.is_poll, n.poll_options, n.poll_expires_at, \
    n.poll_multiple, n.local, \
    a.id AS actor_id, a.username AS actor_username, a.display_name AS actor_display_name, \
    a.avatar_url AS actor_avatar_url, a.header_url AS actor_header_url, \
    a.ap_id AS actor_ap_id, a.domain AS actor_domain, a.is_cat AS actor_is_cat, \
    a.is_bot AS actor_is_bot, a.type AS actor_type, \
    a.manually_approves_followers AS actor_manually_approves_followers, \
    a.discoverable AS actor_discoverable, a.summary AS actor_summary, \
    a.created_at AS actor_created_at";

/// `app.services.note_service.get_note_by_id` 相当(この末端変換に要る列のみ、
/// `deleted_at IS NULL` の削除済みでないノートのみ返す)。
pub async fn fetch_note_render_row(
    db: &PgPool,
    note_id: Uuid,
) -> Result<Option<NoteRenderRow>, AppError> {
    let query = format!(
        "SELECT {NOTE_RENDER_COLUMNS} FROM notes n JOIN actors a ON a.id = n.actor_id \
         WHERE n.id = $1 AND n.deleted_at IS NULL"
    );
    let row = sqlx::query_as::<_, NoteRenderRow>(&query)
        .bind(note_id)
        .fetch_optional(db)
        .await?;
    Ok(row)
}

/// `app/api/mastodon/statuses.py` の `_mime_to_media_type` を移植したもの。
fn mime_to_media_type(mime: &str) -> &'static str {
    if mime.starts_with("image/gif") {
        "gifv"
    } else if mime.starts_with("image/") {
        "image"
    } else if mime.starts_with("video/") {
        "video"
    } else if mime.starts_with("audio/") {
        "audio"
    } else {
        "unknown"
    }
}

fn json_array_truthy(v: Option<&Value>) -> bool {
    v.and_then(|v| v.as_array())
        .map(|a| !a.is_empty())
        .unwrap_or(false)
}

fn str_truthy(v: Option<&str>) -> bool {
    v.map(|s| !s.is_empty()).unwrap_or(false)
}

/// `_attachment_to_media` の `meta` フィールド組み立て部分を移植したもの。
/// drive_file/remote の両系統で同じ組み立て規則(`original`/`focus`/
/// `vision` の3枠)を共有する。
#[allow(clippy::too_many_arguments)]
fn build_attachment_meta(
    width: Option<i32>,
    height: Option<i32>,
    focal_x: Option<f64>,
    focal_y: Option<f64>,
    vision_tags: Option<&Value>,
    vision_caption: Option<&str>,
    duration: Option<f64>,
) -> Value {
    let mut meta = serde_json::Map::new();
    let mut original = serde_json::Map::new();

    if let (Some(w), Some(h)) = (width, height) {
        original.insert("width".into(), json!(w));
        original.insert("height".into(), json!(h));
    }
    if let (Some(x), Some(y)) = (focal_x, focal_y) {
        meta.insert("focus".into(), json!({ "x": x, "y": y }));
    }
    let tags_truthy = json_array_truthy(vision_tags);
    let caption_truthy = str_truthy(vision_caption);
    if tags_truthy || caption_truthy {
        let mut vision = serde_json::Map::new();
        if tags_truthy {
            vision.insert("tags".into(), vision_tags.cloned().unwrap());
        }
        if caption_truthy {
            vision.insert("caption".into(), json!(vision_caption.unwrap()));
        }
        meta.insert("vision".into(), Value::Object(vision));
    }
    if let Some(duration) = duration {
        original.insert("duration".into(), json!(duration));
    }
    if !original.is_empty() {
        meta.insert("original".into(), Value::Object(original));
    }
    if meta.is_empty() {
        Value::Null
    } else {
        Value::Object(meta)
    }
}

#[derive(sqlx::FromRow)]
struct MediaAttachmentRow {
    id: Uuid,
    remote_url: Option<String>,
    remote_mime_type: Option<String>,
    remote_description: Option<String>,
    remote_blurhash: Option<String>,
    remote_width: Option<i32>,
    remote_height: Option<i32>,
    remote_focal_x: Option<f64>,
    remote_focal_y: Option<f64>,
    remote_vision_tags: Option<Value>,
    remote_vision_caption: Option<String>,
    remote_thumbnail_url: Option<String>,
    remote_duration: Option<f64>,
    df_s3_key: Option<String>,
    df_mime_type: Option<String>,
    df_description: Option<String>,
    df_blurhash: Option<String>,
    df_width: Option<i32>,
    df_height: Option<i32>,
    df_focal_x: Option<f64>,
    df_focal_y: Option<f64>,
    df_vision_tags: Option<Value>,
    df_vision_caption: Option<String>,
    df_thumbnail_s3_key: Option<String>,
    df_duration: Option<f64>,
}

/// `app/api/mastodon/statuses.py` の `_attachment_to_media` を移植したもの。
/// `att.drive_file`/`att.remote_url` のいずれも無い(壊れた)添付は
/// Python版の `if att.drive_file or att.remote_url:` と同様スキップする。
fn attachment_to_media_json(config: &Config, att: &MediaAttachmentRow) -> Option<Value> {
    if let Some(s3_key) = &att.df_s3_key {
        let mime = att.df_mime_type.as_deref().unwrap_or("");
        let url = format!("{}/{s3_key}", config.media_url());
        let preview = att
            .df_thumbnail_s3_key
            .as_ref()
            .map(|key| format!("{}/{key}", config.media_url()))
            .unwrap_or_else(|| url.clone());
        let meta = build_attachment_meta(
            att.df_width,
            att.df_height,
            att.df_focal_x,
            att.df_focal_y,
            att.df_vision_tags.as_ref(),
            att.df_vision_caption.as_deref(),
            att.df_duration,
        );
        Some(json!({
            "id": att.id.to_string(),
            "type": mime_to_media_type(mime),
            "url": url,
            "preview_url": preview,
            "remote_url": Value::Null,
            "description": att.df_description,
            "blurhash": att.df_blurhash,
            "meta": meta,
        }))
    } else if let Some(remote_url) = &att.remote_url {
        let mime = att.remote_mime_type.as_deref().unwrap_or("");
        let meta = build_attachment_meta(
            att.remote_width,
            att.remote_height,
            att.remote_focal_x,
            att.remote_focal_y,
            att.remote_vision_tags.as_ref(),
            att.remote_vision_caption.as_deref(),
            att.remote_duration,
        );
        let proxied = media_proxy_url(config, Some(remote_url), None, false);
        let preview = if att
            .remote_thumbnail_url
            .as_deref()
            .is_some_and(|_| mime.starts_with("video/"))
        {
            media_proxy_url(
                config,
                att.remote_thumbnail_url.as_deref(),
                Some("preview"),
                false,
            )
        } else {
            media_proxy_url(config, Some(remote_url), Some("preview"), false)
        };
        Some(json!({
            "id": att.id.to_string(),
            "type": mime_to_media_type(mime),
            "url": proxied,
            "preview_url": preview,
            "remote_url": remote_url,
            "description": att.remote_description,
            "blurhash": att.remote_blurhash,
            "meta": meta,
        }))
    } else {
        None
    }
}

async fn fetch_media_attachments_json(
    db: &PgPool,
    config: &Config,
    note_id: Uuid,
) -> Result<Vec<Value>, AppError> {
    let rows = sqlx::query_as::<_, MediaAttachmentRow>(
        r#"
        SELECT na.id,
               na.remote_url, na.remote_mime_type, na.remote_description, na.remote_blurhash,
               na.remote_width, na.remote_height, na.remote_focal_x, na.remote_focal_y,
               na.remote_vision_tags, na.remote_vision_caption, na.remote_thumbnail_url,
               na.remote_duration,
               df.s3_key AS df_s3_key, df.mime_type AS df_mime_type,
               df.description AS df_description, df.blurhash AS df_blurhash,
               df.width AS df_width, df.height AS df_height,
               df.focal_x AS df_focal_x, df.focal_y AS df_focal_y,
               df.vision_tags AS df_vision_tags, df.vision_caption AS df_vision_caption,
               df.thumbnail_s3_key AS df_thumbnail_s3_key, df.duration AS df_duration
        FROM note_attachments na
        LEFT JOIN drive_files df ON df.id = na.drive_file_id
        WHERE na.note_id = $1
        ORDER BY na.position
        "#,
    )
    .bind(note_id)
    .fetch_all(db)
    .await?;

    Ok(rows
        .iter()
        .filter_map(|att| attachment_to_media_json(config, att))
        .collect())
}

#[derive(sqlx::FromRow, Clone)]
struct NoteEmojiRow {
    shortcode: String,
    url: String,
    static_url: Option<String>,
}

fn note_emoji_json(config: &Config, e: &NoteEmojiRow) -> Value {
    let url = media_proxy_url(config, Some(&e.url), Some("emoji"), false);
    let static_url = match e.static_url.as_deref() {
        Some(su) if !su.is_empty() => media_proxy_url(config, Some(su), Some("emoji"), true),
        _ => media_proxy_url(config, Some(&e.url), Some("emoji"), true),
    };
    json!({
        "shortcode": e.shortcode,
        "url": url,
        "static_url": static_url,
        "visible_in_picker": true,
    })
}

async fn resolve_shortcodes(
    db: &PgPool,
    shortcodes: &HashSet<String>,
    domain: Option<&str>,
) -> Result<Vec<NoteEmojiRow>, AppError> {
    if shortcodes.is_empty() {
        return Ok(Vec::new());
    }
    let codes: Vec<String> = shortcodes.iter().cloned().collect();
    let rows = sqlx::query_as::<_, NoteEmojiRow>(
        "SELECT shortcode, url, static_url FROM custom_emojis \
         WHERE shortcode = ANY($1) AND domain IS NOT DISTINCT FROM $2",
    )
    .bind(&codes)
    .bind(domain)
    .fetch_all(db)
    .await?;
    Ok(rows)
}

/// `note_to_response` の絵文字解決部分 (`content_shortcodes`/`actor_shortcodes`
/// の収集 → ドメイン優先 → ローカルへのフォールバック) を移植したもの。
/// 戻り値は (本文の絵文字, 著者表示名の絵文字)。
async fn resolve_note_and_actor_emojis(
    db: &PgPool,
    config: &Config,
    content: &str,
    actor_display_name: Option<&str>,
    actor_domain: Option<&str>,
) -> Result<(Vec<Value>, Vec<Value>), AppError> {
    let mut content_codes = HashSet::new();
    find_shortcodes(content, &mut content_codes);
    let mut actor_codes = HashSet::new();
    find_shortcodes(actor_display_name.unwrap_or(""), &mut actor_codes);

    let all_codes: HashSet<String> = content_codes.union(&actor_codes).cloned().collect();
    if all_codes.is_empty() {
        return Ok((Vec::new(), Vec::new()));
    }

    let mut emoji_list = resolve_shortcodes(db, &all_codes, actor_domain).await?;
    if actor_domain.is_some() {
        let found: HashSet<&str> = emoji_list.iter().map(|e| e.shortcode.as_str()).collect();
        let missing: HashSet<String> = all_codes
            .iter()
            .filter(|c| !found.contains(c.as_str()))
            .cloned()
            .collect();
        if !missing.is_empty() {
            emoji_list.extend(resolve_shortcodes(db, &missing, None).await?);
        }
    }

    let emoji_map: HashMap<String, Value> = emoji_list
        .iter()
        .map(|e| (e.shortcode.clone(), note_emoji_json(config, e)))
        .collect();
    let content_emojis = content_codes
        .iter()
        .filter_map(|c| emoji_map.get(c).cloned())
        .collect();
    let actor_emojis = actor_codes
        .iter()
        .filter_map(|c| emoji_map.get(c).cloned())
        .collect();
    Ok((content_emojis, actor_emojis))
}

/// `app.services.hashtag_service.get_hashtags_for_note` を移植したもの。
async fn fetch_hashtags_for_note(db: &PgPool, note_id: Uuid) -> Result<Vec<String>, AppError> {
    let names: Vec<String> = sqlx::query_scalar(
        "SELECT h.name FROM hashtags h \
         JOIN note_hashtags nh ON nh.hashtag_id = h.id \
         WHERE nh.note_id = $1",
    )
    .bind(note_id)
    .fetch_all(db)
    .await?;
    Ok(names)
}

fn tag_json(config: &Config, name: &str) -> Value {
    json!({ "name": name, "url": format!("{}/tags/{name}", config.server_url()) })
}

/// `app.services.note_service._CUSTOM_EMOJI_REACTION_RE =
/// re.compile(r"^:([a-zA-Z0-9_]+)(?:@([a-zA-Z0-9.-]+))?:$")` を移植したもの。
/// 完全一致(`^...$`)なので手書きの分解で十分。
fn parse_custom_emoji_reaction(emoji: &str) -> Option<(String, Option<String>)> {
    let inner = emoji.strip_prefix(':')?.strip_suffix(':')?;
    if inner.is_empty() || inner.contains(':') {
        return None;
    }
    let (shortcode, domain) = match inner.split_once('@') {
        Some((sc, dom)) => (sc, Some(dom)),
        None => (inner, None),
    };
    if shortcode.is_empty()
        || !shortcode
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_')
    {
        return None;
    }
    if let Some(dom) = domain {
        if dom.is_empty()
            || !dom
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'.' || b == b'-')
        {
            return None;
        }
    }
    Some((shortcode.to_string(), domain.map(str::to_string)))
}

/// `get_reaction_summary` 内、絵文字リアクション1件ごとの
/// (プロキシ済みURL, importable, import_domain) 解決部分を移植したもの。
async fn resolve_reaction_emoji_url(
    db: &PgPool,
    config: &Config,
    emoji: &str,
) -> Result<(Option<String>, bool, Option<String>), AppError> {
    let Some((shortcode, domain)) = parse_custom_emoji_reaction(emoji) else {
        return Ok((None, false, None));
    };

    let local_url: Option<String> =
        sqlx::query_scalar("SELECT url FROM custom_emojis WHERE shortcode = $1 AND domain IS NULL")
            .bind(&shortcode)
            .fetch_optional(db)
            .await?;

    let mut emoji_url = local_url.clone();
    let mut importable = false;
    let mut import_domain: Option<String> = None;

    if local_url.is_none() {
        if let Some(dom) = &domain {
            let remote_url: Option<String> = sqlx::query_scalar(
                "SELECT url FROM custom_emojis WHERE shortcode = $1 AND domain = $2",
            )
            .bind(&shortcode)
            .bind(dom)
            .fetch_optional(db)
            .await?;
            emoji_url = remote_url;
            importable = true;
            import_domain = Some(dom.clone());
        } else {
            let remote: Option<(Option<String>, String)> = sqlx::query_as(
                "SELECT domain, url FROM custom_emojis \
                 WHERE shortcode = $1 AND domain IS NOT NULL LIMIT 1",
            )
            .bind(&shortcode)
            .fetch_optional(db)
            .await?;
            if let Some((remote_domain, remote_url)) = remote {
                emoji_url = Some(remote_url);
                if let Some(d) = remote_domain {
                    importable = true;
                    import_domain = Some(d);
                }
            }
        }
    }

    let proxied_url = emoji_url.map(|u| media_proxy_url(config, Some(&u), Some("emoji"), false));
    Ok((proxied_url, importable, import_domain))
}

/// `app.services.note_service.get_reaction_summary` を移植したもの。
pub async fn get_reaction_summary(
    db: &PgPool,
    config: &Config,
    note_id: Uuid,
    current_actor_id: Option<Uuid>,
) -> Result<Vec<Value>, AppError> {
    let rows: Vec<(String, i64)> = sqlx::query_as(
        "SELECT emoji, COUNT(*) FROM reactions WHERE note_id = $1 \
         GROUP BY emoji ORDER BY COUNT(*) DESC",
    )
    .bind(note_id)
    .fetch_all(db)
    .await?;

    let my_emojis: HashSet<String> = if let Some(actor_id) = current_actor_id {
        if rows.is_empty() {
            HashSet::new()
        } else {
            sqlx::query_scalar("SELECT emoji FROM reactions WHERE note_id = $1 AND actor_id = $2")
                .bind(note_id)
                .bind(actor_id)
                .fetch_all(db)
                .await?
                .into_iter()
                .collect()
        }
    } else {
        HashSet::new()
    };

    let mut summaries = Vec::with_capacity(rows.len());
    for (emoji, count) in rows {
        let me = my_emojis.contains(&emoji);
        let (emoji_url, importable, import_domain) =
            resolve_reaction_emoji_url(db, config, &emoji).await?;
        let mut entry = json!({
            "emoji": emoji,
            "count": count,
            "me": me,
            "emoji_url": emoji_url,
            "importable": importable,
        });
        if importable {
            entry["import_domain"] = json!(import_domain);
        }
        summaries.push(entry);
    }
    Ok(summaries)
}

/// `app.services.poll_service.get_poll_data` を移植したもの。呼び出し側が
/// 既に `note` を保持している(`note_to_response` がそうであるように)前提で
/// `note` を再フェッチしない点だけがPython版と異なる(冗長クエリの削減、
/// 挙動は同一)。
pub async fn get_poll_data_json(
    db: &PgPool,
    note_id: Uuid,
    poll_options: &Value,
    poll_expires_at: Option<DateTime<Utc>>,
    poll_multiple: bool,
    local: bool,
    current_actor_id: Option<Uuid>,
) -> Result<Value, AppError> {
    let options: Vec<&Value> = poll_options
        .as_array()
        .map(|a| a.iter().collect())
        .unwrap_or_default();

    let (response_options, votes_count): (Vec<Value>, i64) = if local {
        let vote_counts: Vec<(i32, i64)> = sqlx::query_as(
            "SELECT choice_index, COUNT(*) FROM poll_votes WHERE note_id = $1 GROUP BY choice_index",
        )
        .bind(note_id)
        .fetch_all(db)
        .await?;
        let vote_map: HashMap<i32, i64> = vote_counts.into_iter().collect();
        let mut total = 0i64;
        let opts = options
            .iter()
            .enumerate()
            .map(|(i, opt)| {
                let title = opt.get("title").and_then(|v| v.as_str()).unwrap_or("");
                let count = *vote_map.get(&(i as i32)).unwrap_or(&0);
                total += count;
                json!({ "title": title, "votes_count": count })
            })
            .collect();
        (opts, total)
    } else {
        let mut total = 0i64;
        let opts = options
            .iter()
            .map(|opt| {
                let title = opt.get("title").and_then(|v| v.as_str()).unwrap_or("");
                let count = opt.get("votes_count").and_then(|v| v.as_i64()).unwrap_or(0);
                total += count;
                json!({ "title": title, "votes_count": count })
            })
            .collect();
        (opts, total)
    };

    let voters_count: i64 =
        sqlx::query_scalar("SELECT COUNT(DISTINCT actor_id) FROM poll_votes WHERE note_id = $1")
            .bind(note_id)
            .fetch_one(db)
            .await?;

    let expired = poll_expires_at.map(|exp| exp < Utc::now()).unwrap_or(false);

    let (own_votes, voted): (Vec<i32>, bool) = if let Some(actor_id) = current_actor_id {
        let votes: Vec<i32> = sqlx::query_scalar(
            "SELECT choice_index FROM poll_votes WHERE note_id = $1 AND actor_id = $2",
        )
        .bind(note_id)
        .bind(actor_id)
        .fetch_all(db)
        .await?;
        let voted = !votes.is_empty();
        (votes, voted)
    } else {
        (Vec::new(), false)
    };

    Ok(json!({
        "id": note_id.to_string(),
        "expires_at": poll_expires_at.map(|d| d.to_rfc3339()),
        "expired": expired,
        "multiple": poll_multiple,
        "votes_count": votes_count,
        "voters_count": voters_count,
        "options": response_options,
        "voted": voted,
        "own_votes": own_votes,
        "emojis": Vec::<Value>::new(),
    }))
}

#[derive(sqlx::FromRow)]
struct PreviewCardRow {
    url: String,
    title: Option<String>,
    description: Option<String>,
    image: Option<String>,
    card_type: String,
    site_name: Option<String>,
}

/// `_preview_card_to_response` を移植したもの。
async fn fetch_preview_card_json(db: &PgPool, note_id: Uuid) -> Result<Option<Value>, AppError> {
    let row: Option<PreviewCardRow> = sqlx::query_as(
        "SELECT url, title, description, image, card_type, site_name \
         FROM preview_cards WHERE note_id = $1",
    )
    .bind(note_id)
    .fetch_optional(db)
    .await?;
    Ok(row.map(|c| {
        json!({
            "url": c.url,
            "title": c.title.unwrap_or_default(),
            "description": c.description.unwrap_or_default(),
            "image": c.image,
            "type": c.card_type,
            "author_name": "",
            "author_url": "",
            "provider_name": c.site_name.unwrap_or_default(),
            "provider_url": "",
            "html": "",
            "width": 0,
            "height": 0,
            "embed_url": "",
            "blurhash": Value::Null,
        })
    }))
}

/// `note_to_response` の返信先メンション解決部分 (`in_reply_to`/
/// `get_note_by_id` フォールバック)を移植したもの。戻り値は
/// (in_reply_to_account_id, mentions配列に積む1件)。
async fn resolve_reply_mention(
    db: &PgPool,
    in_reply_to_id: Option<Uuid>,
) -> Result<(Option<Uuid>, Option<Value>), AppError> {
    let Some(parent_id) = in_reply_to_id else {
        return Ok((None, None));
    };
    #[derive(sqlx::FromRow)]
    struct ParentRow {
        actor_id: Uuid,
        username: String,
        domain: Option<String>,
        ap_id: String,
    }
    let row: Option<ParentRow> = sqlx::query_as(
        "SELECT n.actor_id, a.username, a.domain, a.ap_id \
         FROM notes n JOIN actors a ON a.id = n.actor_id \
         WHERE n.id = $1 AND n.deleted_at IS NULL",
    )
    .bind(parent_id)
    .fetch_optional(db)
    .await?;
    let Some(row) = row else {
        return Ok((None, None));
    };
    let acct = match &row.domain {
        Some(d) => format!("{}@{d}", row.username),
        None => row.username.clone(),
    };
    let mention = json!({
        "id": row.actor_id.to_string(),
        "username": row.username,
        "acct": acct,
        "url": row.ap_id,
    });
    Ok((Some(row.actor_id), Some(mention)))
}

/// `app.utils.nodeinfo.get_domain_software_info` のうち、Valkey キャッシュを
/// 読むだけの部分を移植したもの。キャッシュミス時は生フェッチ
/// (`_fetch_software`)をせず `(None, None, None)` を返す(モジュール冒頭の
/// コメント参照)。
async fn get_domain_software_info_cached(
    redis: &redis::aio::ConnectionManager,
    domain: &str,
) -> Result<(Option<String>, Option<String>, Option<String>), AppError> {
    let mut conn = redis.clone();
    let cached_name: Option<String> = conn.get(format!("nodeinfo:software:{domain}")).await?;
    let Some(name_val) = cached_name else {
        return Ok((None, None, None));
    };
    let name = (!name_val.is_empty()).then_some(name_val);
    let cached_ver: Option<String> = conn
        .get(format!("nodeinfo:software_version:{domain}"))
        .await?;
    let ver = cached_ver.filter(|v| !v.is_empty());
    let cached_iname: Option<String> = conn.get(format!("nodeinfo:instance_name:{domain}")).await?;
    let iname = cached_iname.filter(|v| !v.is_empty());
    Ok((name, ver, iname))
}

/// `note_to_response` のアクター(`NoteActorResponse`)描画部分を移植したもの。
async fn build_note_actor_json(
    config: &Config,
    redis: &redis::aio::ConnectionManager,
    note: &NoteRenderRow,
    actor_emojis: Vec<Value>,
) -> Result<Value, AppError> {
    let avatar_proxy = media_proxy_url(
        config,
        note.actor_avatar_url.as_deref(),
        Some("avatar"),
        false,
    );
    let avatar = if avatar_proxy.is_empty() {
        format!("{}/default-avatar.svg", config.server_url())
    } else {
        avatar_proxy
    };
    let header = media_proxy_url(config, note.actor_header_url.as_deref(), None, false);
    let acct = match &note.actor_domain {
        Some(d) => format!("{}@{d}", note.actor_username),
        None => note.actor_username.clone(),
    };
    let actor_url = format!("{}/@{acct}", config.server_url());

    let (sw, sw_ver, sw_name) = match &note.actor_domain {
        Some(domain) => get_domain_software_info_cached(redis, domain).await?,
        None => (None, None, None),
    };

    Ok(json!({
        "id": note.actor_id.to_string(),
        "username": note.actor_username,
        "display_name": note.actor_display_name.clone().unwrap_or_default(),
        "avatar_url": avatar,
        "ap_id": note.actor_ap_id,
        "domain": note.actor_domain,
        "server_software": sw,
        "server_software_version": sw_ver,
        "server_name": sw_name,
        "emojis": actor_emojis,
        "acct": acct,
        "uri": note.actor_ap_id,
        "url": actor_url,
        "avatar": avatar,
        "avatar_static": avatar,
        "header": header,
        "header_static": header,
        "note": note.actor_summary.clone().unwrap_or_default(),
        "is_cat": note.actor_is_cat,
        "bot": note.actor_is_bot,
        "group": note.actor_type == "Group",
        "created_at": to_mastodon_datetime(note.actor_created_at),
        "followers_count": 0,
        "following_count": 0,
        "statuses_count": 0,
        "locked": note.actor_manually_approves_followers,
        "discoverable": note.actor_discoverable,
        "fields": Vec::<Value>::new(),
        "last_status_at": Value::Null,
    }))
}

/// `app/api/mastodon/statuses.py` の `note_to_response` を移植したもの
/// (モジュール冒頭のコメントの通り、`reblog`/`quote` は解決済みの値を
/// 呼び出し側から受け取る — 再帰ロジック自体は別PR)。
#[allow(clippy::too_many_arguments)]
pub async fn note_to_response_json(
    db: &PgPool,
    config: &Config,
    redis: &redis::aio::ConnectionManager,
    note: &NoteRenderRow,
    reactions: &[Value],
    viewer_actor_id: Option<Uuid>,
    reblog: Option<Value>,
    quote: Option<Value>,
    reblogged: bool,
    pinned: bool,
) -> Result<Value, AppError> {
    let media_attachments = fetch_media_attachments_json(db, config, note.id).await?;

    let (content_emojis, actor_emojis) = resolve_note_and_actor_emojis(
        db,
        config,
        &note.content,
        note.actor_display_name.as_deref(),
        note.actor_domain.as_deref(),
    )
    .await?;

    let tags: Vec<Value> = fetch_hashtags_for_note(db, note.id)
        .await?
        .iter()
        .map(|name| tag_json(config, name))
        .collect();

    let (in_reply_to_account_id, reply_mention) =
        resolve_reply_mention(db, note.in_reply_to_id).await?;

    let edited_at = note.updated_at.map(to_mastodon_datetime);

    let has_poll_options = note
        .poll_options
        .as_ref()
        .and_then(|v| v.as_array())
        .map(|a| !a.is_empty())
        .unwrap_or(false);
    let poll = if note.is_poll && has_poll_options {
        Some(
            get_poll_data_json(
                db,
                note.id,
                note.poll_options.as_ref().unwrap(),
                note.poll_expires_at,
                note.poll_multiple,
                note.local,
                viewer_actor_id,
            )
            .await?,
        )
    } else {
        None
    };

    let mut favourited = false;
    let mut favourites_count: i64 = 0;
    for r in reactions {
        if r.get("emoji").and_then(|v| v.as_str()) == Some("\u{2b50}") {
            favourites_count = r.get("count").and_then(|v| v.as_i64()).unwrap_or(0);
            if r.get("me").and_then(|v| v.as_bool()).unwrap_or(false) {
                favourited = true;
            }
            break;
        }
    }

    let actor_json = build_note_actor_json(config, redis, note, actor_emojis).await?;
    let card = fetch_preview_card_json(db, note.id).await?;

    let reactions_summary: Vec<Value> = reactions
        .iter()
        .map(|r| {
            json!({
                "emoji": r.get("emoji"),
                "count": r.get("count"),
                "me": r.get("me").and_then(|v| v.as_bool()).unwrap_or(false),
                "emoji_url": r.get("emoji_url"),
                "importable": r.get("importable").and_then(|v| v.as_bool()).unwrap_or(false),
                "import_domain": r.get("import_domain"),
            })
        })
        .collect();
    let emoji_reactions: Vec<Value> = reactions
        .iter()
        .map(|r| {
            json!({
                "name": r.get("emoji"),
                "count": r.get("count"),
                "me": r.get("me").and_then(|v| v.as_bool()).unwrap_or(false),
                "url": r.get("emoji_url"),
                "static_url": r.get("emoji_url"),
                "account_ids": Vec::<Value>::new(),
            })
        })
        .collect();

    let visibility = if note.visibility == "followers" {
        "private"
    } else {
        note.visibility.as_str()
    };

    Ok(json!({
        "id": note.id.to_string(),
        "ap_id": note.ap_id,
        "content": note.content,
        "source": note.source,
        "visibility": visibility,
        "sensitive": note.sensitive,
        "spoiler_text": note.spoiler_text.clone().unwrap_or_default(),
        "published": to_mastodon_datetime(note.published),
        "edited_at": edited_at,
        "replies_count": note.replies_count,
        "reactions_count": note.reactions_count,
        "renotes_count": note.renotes_count,
        "in_reply_to_id": note.in_reply_to_id.map(|id| id.to_string()),
        "in_reply_to_account_id": in_reply_to_account_id.map(|id| id.to_string()),
        "actor": actor_json,
        "reactions": reactions_summary,
        "emoji_reactions": emoji_reactions,
        "favourited": favourited,
        "reblogged": reblogged,
        "pinned": pinned,
        "reblog": reblog,
        "media_attachments": media_attachments,
        "quote": quote,
        "poll": poll,
        "emojis": content_emojis,
        "tags": tags,
        "card": card,
        "mentions": reply_mention.map(|m| vec![m]).unwrap_or_default(),
        "uri": note.ap_id,
        "url": format!("{}/notes/{}", config.server_url(), note.id),
        "account": actor_json.clone(),
        "created_at": to_mastodon_datetime(note.published),
        "reblogs_count": note.renotes_count,
        "favourites_count": favourites_count,
        "muted": false,
        "bookmarked": false,
        "filtered": Vec::<Value>::new(),
        "application": Value::Null,
        "language": Value::Null,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mime_to_media_type_classifies_common_types() {
        assert_eq!(mime_to_media_type("image/gif"), "gifv");
        assert_eq!(mime_to_media_type("image/png"), "image");
        assert_eq!(mime_to_media_type("video/mp4"), "video");
        assert_eq!(mime_to_media_type("audio/mpeg"), "audio");
        assert_eq!(mime_to_media_type("application/pdf"), "unknown");
    }

    #[test]
    fn parse_custom_emoji_reaction_extracts_shortcode_and_domain() {
        assert_eq!(
            parse_custom_emoji_reaction(":blobcat@remote.example:"),
            Some(("blobcat".to_string(), Some("remote.example".to_string())))
        );
        assert_eq!(
            parse_custom_emoji_reaction(":blobcat:"),
            Some(("blobcat".to_string(), None))
        );
    }

    #[test]
    fn parse_custom_emoji_reaction_rejects_plain_unicode_emoji() {
        assert_eq!(parse_custom_emoji_reaction("\u{2b50}"), None);
    }

    #[test]
    fn parse_custom_emoji_reaction_rejects_malformed_strings() {
        assert_eq!(parse_custom_emoji_reaction("::"), None);
        assert_eq!(parse_custom_emoji_reaction(":a:b:"), None);
        assert_eq!(parse_custom_emoji_reaction(":blobcat"), None);
        assert_eq!(parse_custom_emoji_reaction(":blobcat@:"), None);
    }

    #[test]
    fn build_attachment_meta_is_null_when_nothing_present() {
        assert_eq!(
            build_attachment_meta(None, None, None, None, None, None, None),
            Value::Null
        );
    }

    #[test]
    fn build_attachment_meta_combines_original_focus_and_vision() {
        let tags = json!(["cat", "outdoors"]);
        let meta = build_attachment_meta(
            Some(800),
            Some(600),
            Some(0.5),
            Some(0.25),
            Some(&tags),
            Some("a cat"),
            Some(12.5),
        );
        assert_eq!(meta["original"]["width"], 800);
        assert_eq!(meta["original"]["height"], 600);
        assert_eq!(meta["original"]["duration"], 12.5);
        assert_eq!(meta["focus"]["x"], 0.5);
        assert_eq!(meta["focus"]["y"], 0.25);
        assert_eq!(meta["vision"]["tags"], tags);
        assert_eq!(meta["vision"]["caption"], "a cat");
    }

    #[test]
    fn build_attachment_meta_omits_vision_for_empty_tags_and_caption() {
        let empty_tags = json!([]);
        let meta = build_attachment_meta(None, None, None, None, Some(&empty_tags), Some(""), None);
        assert_eq!(meta, Value::Null);
    }
}
