//! `app/activitypub/renderer.py` のうち Add/Remove/Delete/Announce/Undo
//! アクティビティ、および get_outbox/get_featured が必要とする Create/Note
//! のレンダリングを移植したもの。`AP_CONTEXT` は JSON-LD の意味を保つため
//! 一字一句 Python 側と同一に保つこと。他のアクティビティ(Update等)は、
//! それらを必要とするエンドポイントを移植する際に追加する(今は不要な
//! 先取り実装をしない)。

use chrono::{DateTime, Utc};
use serde::Serialize;
use serde_json::{json, Value};
use std::sync::LazyLock;

/// `app/activitypub/renderer.py:17-46` の `AP_CONTEXT` と一字一句同一。
pub static AP_CONTEXT: LazyLock<Value> = LazyLock::new(|| {
    json!([
        "https://www.w3.org/ns/activitystreams",
        "https://w3id.org/security/v1",
        "https://w3id.org/security/multikey/v1",
        {
            "misskey": "https://misskey-hub.net/ns#",
            "toot": "http://joinmastodon.org/ns#",
            "Emoji": "toot:Emoji",
            "schema": "http://schema.org#",
            "value": "schema:value",
            "discoverable": "toot:discoverable",
            "manuallyApprovesFollowers": "as:manuallyApprovesFollowers",
            "vcard": "http://www.w3.org/2006/vcard/ns#",
            "PropertyValue": "schema:PropertyValue",
            "isCat": "misskey:isCat",
            "_misskey_reaction": "misskey:_misskey_reaction",
            "_misskey_content": "misskey:_misskey_content",
            "_misskey_quote": "misskey:_misskey_quote",
            "_misskey_talk": "misskey:_misskey_talk",
            "_misskey_license": "misskey:_misskey_license",
            "_misskey_requireSigninToViewContents": "misskey:_misskey_requireSigninToViewContents",
            "_misskey_makeNotesFollowersOnlyBefore": "misskey:_misskey_makeNotesFollowersOnlyBefore",
            "_misskey_makeNotesHiddenBefore": "misskey:_misskey_makeNotesHiddenBefore",
            "quoteUrl": "as:quoteUrl",
            "votersCount": "toot:votersCount",
            "featured": {"@id": "toot:featured", "@type": "@id"},
            "movedTo": {"@id": "as:movedTo", "@type": "@id"},
            "alsoKnownAs": {"@id": "as:alsoKnownAs", "@type": "@id"}
        }
    ])
});

/// `app.activitypub.renderer.render_add_activity` を移植したもの。
pub fn render_add_activity(
    activity_id: &str,
    actor_ap_id: &str,
    object_id: &str,
    target: &str,
) -> Value {
    json!({
        "@context": AP_CONTEXT.clone(),
        "id": activity_id,
        "type": "Add",
        "actor": actor_ap_id,
        "object": object_id,
        "target": target,
    })
}

/// `app.activitypub.renderer.render_remove_activity` を移植したもの。
pub fn render_remove_activity(
    activity_id: &str,
    actor_ap_id: &str,
    object_id: &str,
    target: &str,
) -> Value {
    json!({
        "@context": AP_CONTEXT.clone(),
        "id": activity_id,
        "type": "Remove",
        "actor": actor_ap_id,
        "object": object_id,
        "target": target,
    })
}

/// `app.activitypub.renderer.render_delete_activity` を移植したもの。
pub fn render_delete_activity(activity_id: &str, actor_ap_id: &str, object_id: &str) -> Value {
    json!({
        "@context": AP_CONTEXT.clone(),
        "id": activity_id,
        "type": "Delete",
        "actor": actor_ap_id,
        "object": { "id": object_id, "type": "Tombstone" },
    })
}

/// `app.activitypub.renderer.render_announce_activity` を移植したもの。
pub fn render_announce_activity(
    activity_id: &str,
    actor_ap_id: &str,
    note_ap_id: &str,
    to: &Value,
    cc: &Value,
    published: &str,
) -> Value {
    json!({
        "@context": AP_CONTEXT.clone(),
        "id": activity_id,
        "type": "Announce",
        "actor": actor_ap_id,
        "object": note_ap_id,
        "to": to,
        "cc": cc,
        "published": published,
    })
}

/// `app.activitypub.renderer.render_undo_activity` を移植したもの。
pub fn render_undo_activity(activity_id: &str, actor_ap_id: &str, inner_activity: &Value) -> Value {
    json!({
        "@context": AP_CONTEXT.clone(),
        "id": activity_id,
        "type": "Undo",
        "actor": actor_ap_id,
        "object": inner_activity,
    })
}

/// `app.activitypub.renderer.render_update_activity` を移植したもの。
pub fn render_update_activity(activity_id: &str, actor_ap_id: &str, object_data: &Value) -> Value {
    json!({
        "@context": AP_CONTEXT.clone(),
        "id": activity_id,
        "type": "Update",
        "actor": actor_ap_id,
        "object": object_data,
    })
}

/// `render_ordered_collection`/`render_ordered_collection_page` が使う
/// `@context`。`AP_CONTEXT`(security/multikey拡張込み)とは異なり、
/// Python版もここでは素の文字列を使っている。
const PLAIN_AS_CONTEXT: &str = "https://www.w3.org/ns/activitystreams";

/// `app.activitypub.renderer.render_ordered_collection` を移植したもの。
pub fn render_ordered_collection(collection_id: &str, total_items: i64, first_page: &str) -> Value {
    json!({
        "@context": PLAIN_AS_CONTEXT,
        "id": collection_id,
        "type": "OrderedCollection",
        "totalItems": total_items,
        "first": first_page,
    })
}

/// `app.activitypub.renderer.render_ordered_collection_page` を移植したもの。
/// Python版の呼び出し元(outbox/followers/following)はいずれも`next_page`を
/// 渡していない(2ページ目以降のページネーションが実質未実装)ため、
/// このRust版でもその挙動をそのまま踏襲し`next`引数は設けない。
pub fn render_ordered_collection_page(
    page_id: &str,
    part_of: &str,
    items: impl Serialize,
) -> Value {
    json!({
        "@context": PLAIN_AS_CONTEXT,
        "id": page_id,
        "type": "OrderedCollectionPage",
        "partOf": part_of,
        "orderedItems": items,
    })
}

/// `app/activitypub/renderer.py` の `_iso_z` を移植したもの
/// (マイクロ秒6桁 + 末尾 `Z`、タイムゾーンオフセット表記は使わない)。
pub fn iso_z(dt: DateTime<Utc>) -> String {
    dt.format("%Y-%m-%dT%H:%M:%S%.6fZ").to_string()
}

/// `app.activitypub.resolve_source_media_type` を移植したもの。
pub fn resolve_source_media_type(source: &str, preferences: Option<&Value>) -> &'static str {
    let pref = preferences
        .and_then(|p| p.get("source_media_type"))
        .and_then(|v| v.as_str())
        .unwrap_or("auto");
    match pref {
        "mfm" => "text/x.misskeymarkdown",
        "plain" => "text/plain",
        _ if source.contains("$[") => "text/x.misskeymarkdown",
        _ => "text/plain",
    }
}

/// 空文字列を「未設定」として扱う (Python の文字列truthy判定を再現するヘルパー)。
pub fn truthy_string(s: Option<String>) -> Option<String> {
    s.filter(|v| !v.is_empty())
}

/// `app/activitypub/renderer.py` の `render_note` が `note.attachments` から
/// 組み立てる `Document` タグ1件分。`NoteAttachment`(drive_file/remote の
/// 2系統)を呼び出し側で解決した後の共通表現。
#[derive(Debug, Clone, Default)]
pub struct NoteAttachmentData {
    pub media_type: String,
    pub url: String,
    pub name: String,
    pub width: Option<i32>,
    pub height: Option<i32>,
    pub blurhash: Option<String>,
    pub focal_point: Option<[f64; 2]>,
    /// 動画サムネイル (`att.drive_file.thumbnail_s3_key`)。Python版は
    /// remote添付では参照しないため、drive_file系のみで埋まる。
    pub icon: Option<(String, String)>,
    pub duration: Option<f64>,
}

/// `app/activitypub/renderer.py` の `render_note` が `note._hashtag_names` から
/// 組み立てる `Hashtag` タグ1件分。`href` は呼び出し側が
/// `{server_url}/tags/{name}` の形で組み立て済みのものを渡す
/// (`render_note` 自体は `server_url` を知らない設計を保つため)。
#[derive(Debug, Clone)]
pub struct HashtagTagData {
    pub name: String,
    pub href: String,
}

/// `app/activitypub/renderer.py` の `render_note` が `note._emoji_tags` から
/// 組み立てる `Emoji` タグ1件分。`id` は呼び出し側が
/// `{server_url}/emojis/{shortcode}` の形で組み立て済みのものを渡す。
/// Python版の `category` フィールドはAPタグ描画に使われないため、
/// この構造体にも含めない。
#[derive(Debug, Clone)]
pub struct EmojiTagData {
    pub id: String,
    pub shortcode: String,
    pub url: String,
    pub aliases: Option<Value>,
    pub license: Option<String>,
    pub is_sensitive: bool,
    pub author: Option<String>,
    pub description: Option<String>,
    pub copy_permission: Option<String>,
    pub usage_info: Option<String>,
    pub is_based_on: Option<String>,
}

/// `app/activitypub/renderer.py` の `render_note` が必要とする、
/// DB行(actor/attachments込み)から呼び出し側が解決済みのノートデータ。
/// `get_outbox`/`get_featured` はいずれもレンダリング対象ノートが単一の
/// ローカルactorに属することが確定しているため(`note.actor`を都度引く
/// 必要がない)、`attributed_to`/`note_url`は文字列として渡す設計にしている。
/// ハッシュタグ・カスタム絵文字タグは Python版でもこの2エンドポイントでは
/// 動的属性 (`_hashtag_names`/`_emoji_tags`) が未設定のため描画されない
/// (`get_note_ap`/`create_status` だけがこれらを設定する) — 該当フィールドは
/// 空の `Vec` を渡す。
pub struct NoteRenderData {
    pub ap_id: String,
    pub is_poll: bool,
    pub attributed_to: String,
    pub content: String,
    pub published: DateTime<Utc>,
    pub to: Value,
    pub cc: Value,
    pub note_url: String,
    pub updated_at: Option<DateTime<Utc>>,
    pub source: Option<String>,
    /// `source` が `Some` の場合のみ意味を持つ、事前解決済みの `resolve_source_media_type` 結果。
    pub source_media_type: Option<String>,
    pub sensitive: bool,
    pub spoiler_text: Option<String>,
    pub in_reply_to_ap_id: Option<String>,
    pub quote_ap_id: Option<String>,
    pub mentions: Option<Value>,
    pub attachments: Vec<NoteAttachmentData>,
    pub poll_options: Option<Value>,
    pub poll_expires_at: Option<DateTime<Utc>>,
    pub poll_multiple: bool,
    pub is_talk: bool,
    pub hashtags: Vec<HashtagTagData>,
    pub emoji_tags: Vec<EmojiTagData>,
}

/// `app/activitypub/renderer.py` の `render_note` を移植したもの。
pub fn render_note(note: &NoteRenderData) -> Value {
    let note_type = if note.is_poll { "Question" } else { "Note" };
    let mut data = json!({
        "@context": AP_CONTEXT.clone(),
        "id": note.ap_id,
        "type": note_type,
        "attributedTo": note.attributed_to,
        "content": note.content,
        "published": iso_z(note.published),
        "to": note.to,
        "cc": note.cc,
        "url": note.note_url,
    });

    if let Some(updated_at) = note.updated_at {
        data["updated"] = json!(iso_z(updated_at));
    }
    if let Some(source) = note.source.as_deref().filter(|s| !s.is_empty()) {
        let media_type = note.source_media_type.as_deref().unwrap_or("text/plain");
        data["source"] = json!({ "content": source, "mediaType": media_type });
        data["_misskey_content"] = json!(source);
    }
    if note.sensitive {
        data["sensitive"] = json!(true);
    }
    if let Some(spoiler) = note.spoiler_text.as_deref().filter(|s| !s.is_empty()) {
        data["summary"] = json!(spoiler);
    }
    if let Some(in_reply_to) = note.in_reply_to_ap_id.as_deref().filter(|s| !s.is_empty()) {
        data["inReplyTo"] = json!(in_reply_to);
    }
    if let Some(quote) = note.quote_ap_id.as_deref().filter(|s| !s.is_empty()) {
        data["_misskey_quote"] = json!(quote);
        data["quoteUrl"] = json!(quote);
    }

    if !note.attachments.is_empty() {
        let attachment_list: Vec<Value> = note
            .attachments
            .iter()
            .map(|att| {
                let mut doc = json!({
                    "type": "Document",
                    "mediaType": att.media_type,
                    "url": att.url,
                    "name": att.name,
                });
                if let (Some(width), Some(height)) = (att.width, att.height) {
                    doc["width"] = json!(width);
                    doc["height"] = json!(height);
                }
                if let Some(blurhash) = &att.blurhash {
                    doc["blurhash"] = json!(blurhash);
                }
                if let Some([x, y]) = att.focal_point {
                    doc["focalPoint"] = json!([x, y]);
                }
                if let Some((icon_media_type, icon_url)) = &att.icon {
                    doc["icon"] = json!({
                        "type": "Image",
                        "mediaType": icon_media_type,
                        "url": icon_url,
                    });
                }
                if let Some(duration) = att.duration {
                    doc["duration"] = json!(format!("PT{duration:.1}S"));
                }
                doc
            })
            .collect();
        data["attachment"] = json!(attachment_list);
    }

    // タグ (メンション + ハッシュタグ + カスタム絵文字)。
    let mut tag: Vec<Value> = Vec::new();
    if let Some(mentions) = note.mentions.as_ref().and_then(|v| v.as_array()) {
        for m in mentions {
            let username = m
                .get("username")
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty());
            let name = if let Some(username) = username {
                match m
                    .get("domain")
                    .and_then(|v| v.as_str())
                    .filter(|s| !s.is_empty())
                {
                    Some(domain) => format!("@{username}@{domain}"),
                    None => format!("@{username}"),
                }
            } else {
                m.get("name")
                    .and_then(|v| v.as_str())
                    .filter(|s| !s.is_empty())
                    .or_else(|| m.get("ap_id").and_then(|v| v.as_str()))
                    .unwrap_or("")
                    .to_string()
            };
            tag.push(json!({
                "type": "Mention",
                "href": m.get("ap_id").and_then(|v| v.as_str()).unwrap_or(""),
                "name": name,
            }));
        }
    }

    for ht in &note.hashtags {
        tag.push(json!({
            "type": "Hashtag",
            "href": ht.href,
            "name": format!("#{}", ht.name),
        }));
    }

    for e in &note.emoji_tags {
        let ext = e
            .url
            .rsplit_once('.')
            .map(|(_, ext)| ext.to_lowercase())
            .unwrap_or_else(|| "png".to_string());
        let media_type = match ext.as_str() {
            "png" => "image/png",
            "jpg" | "jpeg" => "image/jpeg",
            "gif" => "image/gif",
            "webp" => "image/webp",
            "avif" => "image/avif",
            "svg" => "image/svg+xml",
            _ => "image/png",
        };
        let mut emoji_tag = json!({
            "id": e.id,
            "type": "Emoji",
            "name": format!(":{}:", e.shortcode),
            "icon": { "type": "Image", "mediaType": media_type, "url": e.url },
        });
        if let Some(license) = &e.license {
            emoji_tag["_misskey_license"] = json!({ "freeText": license });
            emoji_tag["license"] = json!(license);
        }
        if let Some(aliases) = e
            .aliases
            .as_ref()
            .filter(|v| v.as_array().is_some_and(|a| !a.is_empty()))
        {
            emoji_tag["keywords"] = aliases.clone();
        }
        if e.is_sensitive {
            emoji_tag["isSensitive"] = json!(true);
        }
        if let Some(author) = &e.author {
            emoji_tag["author"] = json!(author);
        }
        if let Some(description) = &e.description {
            emoji_tag["description"] = json!(description);
        }
        if let Some(copy_permission) = &e.copy_permission {
            emoji_tag["copyPermission"] = json!(copy_permission);
        }
        if let Some(usage_info) = &e.usage_info {
            emoji_tag["usageInfo"] = json!(usage_info);
        }
        if let Some(is_based_on) = &e.is_based_on {
            emoji_tag["isBasedOn"] = json!(is_based_on);
        }
        tag.push(emoji_tag);
    }

    if !tag.is_empty() {
        data["tag"] = json!(tag);
    }

    if note.is_poll {
        if let Some(options) = note
            .poll_options
            .as_ref()
            .and_then(|v| v.as_array())
            .filter(|opts| !opts.is_empty())
        {
            let choices_key = if note.poll_multiple { "anyOf" } else { "oneOf" };
            let choices: Vec<Value> = options
                .iter()
                .map(|opt| {
                    json!({
                        "type": "Note",
                        "name": opt.get("title").and_then(|v| v.as_str()).unwrap_or(""),
                        "replies": {
                            "type": "Collection",
                            "totalItems": opt.get("votes_count").and_then(|v| v.as_i64()).unwrap_or(0),
                        },
                    })
                })
                .collect();
            data[choices_key] = json!(choices);
            if let Some(expires_at) = note.poll_expires_at {
                data["endTime"] = json!(iso_z(expires_at));
            }
            let total_votes: i64 = options
                .iter()
                .map(|opt| opt.get("votes_count").and_then(|v| v.as_i64()).unwrap_or(0))
                .sum();
            data["votersCount"] = json!(total_votes);
        }
    }

    if note.is_talk {
        data["_misskey_talk"] = json!(true);
    }

    data
}

/// `app/activitypub/renderer.py` の `render_create_activity` を移植したもの。
pub fn render_create_activity(note: &NoteRenderData) -> Value {
    json!({
        "@context": AP_CONTEXT.clone(),
        "id": format!("{}/activity", note.ap_id),
        "type": "Create",
        "actor": note.attributed_to,
        "object": render_note(note),
        "to": note.to,
        "cc": note.cc,
        "published": iso_z(note.published),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    /// `app/activitypub/renderer.py` の `AP_CONTEXT` と要素数・内容が
    /// 一致することを固定値で検証する(手作業コピーのtypo検出用)。
    #[test]
    fn ap_context_matches_python_renderer() {
        let expected = json!([
            "https://www.w3.org/ns/activitystreams",
            "https://w3id.org/security/v1",
            "https://w3id.org/security/multikey/v1",
            {
                "misskey": "https://misskey-hub.net/ns#",
                "toot": "http://joinmastodon.org/ns#",
                "Emoji": "toot:Emoji",
                "schema": "http://schema.org#",
                "value": "schema:value",
                "discoverable": "toot:discoverable",
                "manuallyApprovesFollowers": "as:manuallyApprovesFollowers",
                "vcard": "http://www.w3.org/2006/vcard/ns#",
                "PropertyValue": "schema:PropertyValue",
                "isCat": "misskey:isCat",
                "_misskey_reaction": "misskey:_misskey_reaction",
                "_misskey_content": "misskey:_misskey_content",
                "_misskey_quote": "misskey:_misskey_quote",
                "_misskey_talk": "misskey:_misskey_talk",
                "_misskey_license": "misskey:_misskey_license",
                "_misskey_requireSigninToViewContents": "misskey:_misskey_requireSigninToViewContents",
                "_misskey_makeNotesFollowersOnlyBefore": "misskey:_misskey_makeNotesFollowersOnlyBefore",
                "_misskey_makeNotesHiddenBefore": "misskey:_misskey_makeNotesHiddenBefore",
                "quoteUrl": "as:quoteUrl",
                "votersCount": "toot:votersCount",
                "featured": {"@id": "toot:featured", "@type": "@id"},
                "movedTo": {"@id": "as:movedTo", "@type": "@id"},
                "alsoKnownAs": {"@id": "as:alsoKnownAs", "@type": "@id"}
            }
        ]);
        assert_eq!(*AP_CONTEXT, expected);
    }

    #[test]
    fn render_add_activity_matches_python_shape() {
        let activity = render_add_activity(
            "https://example.com/add/1",
            "https://example.com/users/alice",
            "https://example.com/notes/1",
            "https://example.com/users/alice/featured",
        );
        assert_eq!(activity["type"], "Add");
        assert_eq!(activity["id"], "https://example.com/add/1");
        assert_eq!(activity["actor"], "https://example.com/users/alice");
        assert_eq!(activity["object"], "https://example.com/notes/1");
        assert_eq!(
            activity["target"],
            "https://example.com/users/alice/featured"
        );
        assert_eq!(activity["@context"], *AP_CONTEXT);
    }

    #[test]
    fn render_delete_activity_wraps_object_in_tombstone() {
        let activity = render_delete_activity(
            "https://example.com/notes/1/delete",
            "https://example.com/users/alice",
            "https://example.com/notes/1",
        );
        assert_eq!(activity["type"], "Delete");
        assert_eq!(activity["id"], "https://example.com/notes/1/delete");
        assert_eq!(activity["actor"], "https://example.com/users/alice");
        assert_eq!(activity["object"]["id"], "https://example.com/notes/1");
        assert_eq!(activity["object"]["type"], "Tombstone");
        assert_eq!(activity["@context"], *AP_CONTEXT);
    }

    #[test]
    fn render_announce_activity_matches_python_shape() {
        let to = json!(["https://www.w3.org/ns/activitystreams#Public"]);
        let cc = json!(["https://example.com/users/alice/followers"]);
        let activity = render_announce_activity(
            "https://example.com/notes/2",
            "https://example.com/users/alice",
            "https://example.com/notes/1",
            &to,
            &cc,
            "2026-01-01T00:00:00.000Z",
        );
        assert_eq!(activity["type"], "Announce");
        assert_eq!(activity["id"], "https://example.com/notes/2");
        assert_eq!(activity["actor"], "https://example.com/users/alice");
        assert_eq!(activity["object"], "https://example.com/notes/1");
        assert_eq!(activity["to"], to);
        assert_eq!(activity["cc"], cc);
        assert_eq!(activity["published"], "2026-01-01T00:00:00.000Z");
        assert_eq!(activity["@context"], *AP_CONTEXT);
    }

    #[test]
    fn render_undo_activity_wraps_inner_activity() {
        let inner = json!({ "type": "Announce", "id": "https://example.com/notes/2" });
        let activity = render_undo_activity(
            "https://example.com/notes/2/undo",
            "https://example.com/users/alice",
            &inner,
        );
        assert_eq!(activity["type"], "Undo");
        assert_eq!(activity["id"], "https://example.com/notes/2/undo");
        assert_eq!(activity["actor"], "https://example.com/users/alice");
        assert_eq!(activity["object"], inner);
        assert_eq!(activity["@context"], *AP_CONTEXT);
    }

    #[test]
    fn render_update_activity_wraps_object_data() {
        let object_data = json!({ "type": "Note", "id": "https://example.com/notes/1" });
        let activity = render_update_activity(
            "https://example.com/notes/1/update/1234567890",
            "https://example.com/users/alice",
            &object_data,
        );
        assert_eq!(activity["type"], "Update");
        assert_eq!(
            activity["id"],
            "https://example.com/notes/1/update/1234567890"
        );
        assert_eq!(activity["actor"], "https://example.com/users/alice");
        assert_eq!(activity["object"], object_data);
        assert_eq!(activity["@context"], *AP_CONTEXT);
    }

    #[test]
    fn render_ordered_collection_matches_python_shape() {
        let collection = render_ordered_collection(
            "https://example.com/users/alice/followers",
            3,
            "https://example.com/users/alice/followers?page=true",
        );
        assert_eq!(collection["@context"], PLAIN_AS_CONTEXT);
        assert_eq!(collection["type"], "OrderedCollection");
        assert_eq!(collection["totalItems"], 3);
        assert_eq!(
            collection["first"],
            "https://example.com/users/alice/followers?page=true"
        );
    }

    #[test]
    fn render_ordered_collection_page_matches_python_shape_and_has_no_next() {
        let page = render_ordered_collection_page(
            "https://example.com/users/alice/followers?page=true",
            "https://example.com/users/alice/followers",
            vec!["https://remote.example/users/bob"],
        );
        assert_eq!(page["type"], "OrderedCollectionPage");
        assert_eq!(page["orderedItems"][0], "https://remote.example/users/bob");
        assert!(page.get("next").is_none());
    }

    fn minimal_note() -> NoteRenderData {
        NoteRenderData {
            ap_id: "https://localhost/notes/1".into(),
            is_poll: false,
            attributed_to: "https://localhost/users/alice".into(),
            content: "<p>hello</p>".into(),
            published: DateTime::parse_from_rfc3339("2026-01-01T00:00:00Z")
                .unwrap()
                .with_timezone(&Utc),
            to: json!(["https://www.w3.org/ns/activitystreams#Public"]),
            cc: json!([]),
            note_url: "https://localhost/notes/1".into(),
            updated_at: None,
            source: None,
            source_media_type: None,
            sensitive: false,
            spoiler_text: None,
            in_reply_to_ap_id: None,
            quote_ap_id: None,
            mentions: None,
            attachments: Vec::new(),
            poll_options: None,
            poll_expires_at: None,
            poll_multiple: false,
            is_talk: false,
            hashtags: Vec::new(),
            emoji_tags: Vec::new(),
        }
    }

    #[test]
    fn render_note_minimal_matches_python_shape() {
        let note = minimal_note();
        let data = render_note(&note);
        assert_eq!(data["type"], "Note");
        assert_eq!(data["id"], "https://localhost/notes/1");
        assert_eq!(data["attributedTo"], "https://localhost/users/alice");
        assert_eq!(data["content"], "<p>hello</p>");
        assert!(data.get("source").is_none());
        assert!(data.get("sensitive").is_none());
        assert!(data.get("attachment").is_none());
        assert!(data.get("tag").is_none());
    }

    #[test]
    fn render_note_is_poll_uses_question_type() {
        let mut note = minimal_note();
        note.is_poll = true;
        let data = render_note(&note);
        assert_eq!(data["type"], "Question");
    }

    #[test]
    fn render_note_empty_optional_strings_are_omitted() {
        let mut note = minimal_note();
        note.spoiler_text = Some(String::new());
        note.in_reply_to_ap_id = Some(String::new());
        note.quote_ap_id = Some(String::new());
        note.source = Some(String::new());
        let data = render_note(&note);
        assert!(data.get("summary").is_none());
        assert!(data.get("inReplyTo").is_none());
        assert!(data.get("quoteUrl").is_none());
        assert!(data.get("source").is_none());
    }

    #[test]
    fn render_note_includes_source_and_misskey_content() {
        let mut note = minimal_note();
        note.source = Some("plain text".into());
        note.source_media_type = Some("text/plain".into());
        let data = render_note(&note);
        assert_eq!(data["source"]["content"], "plain text");
        assert_eq!(data["source"]["mediaType"], "text/plain");
        assert_eq!(data["_misskey_content"], "plain text");
    }

    #[test]
    fn render_note_quote_sets_both_misskey_quote_and_quote_url() {
        let mut note = minimal_note();
        note.quote_ap_id = Some("https://localhost/notes/2".into());
        let data = render_note(&note);
        assert_eq!(data["_misskey_quote"], "https://localhost/notes/2");
        assert_eq!(data["quoteUrl"], "https://localhost/notes/2");
    }

    #[test]
    fn render_note_mention_with_domain_renders_full_handle() {
        let mut note = minimal_note();
        note.mentions = Some(json!([
            {"ap_id": "https://remote.example/users/bob", "username": "bob", "domain": "remote.example"}
        ]));
        let data = render_note(&note);
        assert_eq!(data["tag"][0]["type"], "Mention");
        assert_eq!(data["tag"][0]["href"], "https://remote.example/users/bob");
        assert_eq!(data["tag"][0]["name"], "@bob@remote.example");
    }

    #[test]
    fn render_note_mention_without_username_falls_back_to_name_or_ap_id() {
        let mut note = minimal_note();
        note.mentions = Some(json!([
            {"ap_id": "https://remote.example/users/carol", "name": "Carol"}
        ]));
        let data = render_note(&note);
        assert_eq!(data["tag"][0]["name"], "Carol");

        note.mentions = Some(json!([{"ap_id": "https://remote.example/users/dave"}]));
        let data = render_note(&note);
        assert_eq!(data["tag"][0]["name"], "https://remote.example/users/dave");
    }

    #[test]
    fn render_note_attachment_includes_drive_file_fields() {
        let mut note = minimal_note();
        note.attachments = vec![NoteAttachmentData {
            media_type: "image/png".into(),
            url: "https://localhost/media/abc.png".into(),
            name: "a cat".into(),
            width: Some(100),
            height: Some(200),
            blurhash: Some("LKO2?U%2Tw=w".into()),
            focal_point: Some([0.1, -0.2]),
            icon: Some((
                "image/webp".into(),
                "https://localhost/media/thumb.webp".into(),
            )),
            duration: Some(12.5),
        }];
        let data = render_note(&note);
        let doc = &data["attachment"][0];
        assert_eq!(doc["type"], "Document");
        assert_eq!(doc["mediaType"], "image/png");
        assert_eq!(doc["width"], 100);
        assert_eq!(doc["height"], 200);
        assert_eq!(doc["blurhash"], "LKO2?U%2Tw=w");
        assert_eq!(doc["focalPoint"], json!([0.1, -0.2]));
        assert_eq!(doc["icon"]["mediaType"], "image/webp");
        assert_eq!(doc["duration"], "PT12.5S");
    }

    #[test]
    fn render_note_poll_renders_one_of_and_voters_count() {
        let mut note = minimal_note();
        note.is_poll = true;
        note.poll_options = Some(json!([
            {"title": "cat", "votes_count": 3},
            {"title": "dog", "votes_count": 2},
        ]));
        let data = render_note(&note);
        assert_eq!(data["oneOf"][0]["name"], "cat");
        assert_eq!(data["oneOf"][0]["replies"]["totalItems"], 3);
        assert_eq!(data["votersCount"], 5);
        assert!(data.get("anyOf").is_none());
    }

    #[test]
    fn render_note_poll_multiple_renders_any_of() {
        let mut note = minimal_note();
        note.is_poll = true;
        note.poll_multiple = true;
        note.poll_options = Some(json!([{"title": "cat", "votes_count": 1}]));
        let data = render_note(&note);
        assert!(data.get("oneOf").is_none());
        assert_eq!(data["anyOf"][0]["name"], "cat");
    }

    #[test]
    fn render_create_activity_wraps_note_in_create() {
        let note = minimal_note();
        let activity = render_create_activity(&note);
        assert_eq!(activity["type"], "Create");
        assert_eq!(activity["id"], "https://localhost/notes/1/activity");
        assert_eq!(activity["actor"], "https://localhost/users/alice");
        assert_eq!(activity["object"]["type"], "Note");
        assert_eq!(activity["to"], note.to);
    }

    #[test]
    fn resolve_source_media_type_respects_explicit_preference() {
        assert_eq!(
            resolve_source_media_type("plain $[x]", Some(&json!({"source_media_type": "plain"}))),
            "text/plain"
        );
        assert_eq!(
            resolve_source_media_type("no mfm syntax", Some(&json!({"source_media_type": "mfm"}))),
            "text/x.misskeymarkdown"
        );
    }

    #[test]
    fn resolve_source_media_type_auto_detects_mfm_syntax() {
        assert_eq!(
            resolve_source_media_type("$[tada hi]", None),
            "text/x.misskeymarkdown"
        );
        assert_eq!(resolve_source_media_type("plain text", None), "text/plain");
    }
}
