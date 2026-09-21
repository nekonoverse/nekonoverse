//! `app/activitypub/renderer.py` のうち Add/Remove アクティビティの
//! レンダリングに必要な部分のみを移植したもの。`AP_CONTEXT` は JSON-LD の
//! 意味を保つため一字一句 Python 側と同一に保つこと。Create/Announce/Undo
//! 等の他のアクティビティは、それらを必要とするエンドポイントを移植する
//! 際に追加する(今は不要な先取り実装をしない)。

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
}
