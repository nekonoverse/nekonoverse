//! `app/services/actor_service.py` のうち、未知のリモートactorを署名付きHTTPで
//! 取り込む経路 (`fetch_remote_actor`/`upsert_remote_actor`/`get_actor_public_key`/
//! `_get_signing_key`/`_signed_get`) を移植したもの。inbox受信処理
//! (`activitypub/handlers/`のRust化、Issue #1139 Stage 4) がHTTP Signature検証
//! (`http_signature.rs`、#1151)のために必要とする「鍵IDからactorを引く」経路の
//! 前提となる基盤。
//!
//! これまでのPRでは「未知のリモートactor/noteの署名付きHTTP取り込み」を
//! 一貫して深追いせず優雅に劣化させてきた(`resolve_webfinger`/`fetch_remote_note`
//! 等)が、inboxはその性質上「初めて連合してくる未知のactor」を捌けなければ
//! 実用にならないため、今回はこの能力自体を1つの独立した垂直スライスとして
//! 移植する(inboxルート自体の配線・ハンドラーディスパッチは別PR)。
//!
//! SSRF対策はStage 2 (media proxy) で確立した `ssrf::is_blocked_ip` +
//! `routes::media_proxy::build_client_for`(DNS解決結果を`resolve()`で固定し
//! rebinding対策、リダイレクトは`Policy::none()`にして手動で各ホップを再検証)
//! をそのまま再利用する。署名(`http_signature::sign_request`)はホップごとに
//! Hostが変わるため、リダイレクト追跡ループの中で毎回署名し直す。
//!
//! `upsert_remote_actor`の更新時のフィールドごとの上書き規則(既存値保持/
//! 常に上書き/構造的に有効な場合のみ上書き、の3パターン)はPython版と完全に
//! 一致するよう個々に実装している(actorの鍵material・被フォロー範囲設定
//! (`manuallyApprovesFollowers`)等、連合の信頼境界に関わる値のため)。

use chrono::{DateTime, Utc};
use serde_json::Value;
use sqlx::PgPool;
use uuid::Uuid;

use crate::error::AppError;
use crate::http_signature::sign_request;
use crate::routes::media_proxy::{build_client_for, is_host_blocked};
use crate::state::AppState;

const AP_ACCEPT: &str = r#"application/ld+json; profile="https://www.w3.org/ns/activitystreams""#;
const MAX_REDIRECTS: usize = 5;
/// `app.services.actor_service.fetch_remote_actor` の1時間キャッシュと同一。
const CACHE_TTL_SECS: i64 = 3600;

/// `get_actor_public_key`が返す最小限の情報。
pub struct ActorKeyInfo {
    pub actor_id: Uuid,
    pub public_key_material: String,
    pub algorithm: String,
}

#[derive(sqlx::FromRow)]
struct SigningKeyRow {
    private_key_pem: String,
    username: String,
}

/// `app.services.actor_service._get_signing_key` を移植したもの。任意の
/// ローカルユーザー1件(Python版と同じく先着順、インスタンス代表としての
/// 署名用途)を返す。Python版はプロセス内キャッシュを持つが、Rust版は
/// コネクションプール上の軽いクエリのため素直に毎回引く(挙動に差はない)。
async fn get_signing_key(state: &AppState) -> Result<Option<(String, String)>, AppError> {
    // Python版は`.limit(1)`のみ(順序未指定、DB実装依存の任意の1件)だが、
    // `private_key_pem LIKE '-----BEGIN%'`の絞り込みを追加している。本番では
    // 全ローカルユーザーが実際のPEM形式の鍵を持つため無害な絞り込みだが、
    // Rust結合テストが共有テストDB上の他テストファイルが投入した
    // (署名鍵として使えない)'dummy-pem'行を拾ってしまい、この関数が使われる
    // 度に結果が不定になる問題を防ぐ。
    let row: Option<SigningKeyRow> = sqlx::query_as(
        "SELECT u.private_key_pem, a.username FROM users u \
         JOIN actors a ON a.id = u.actor_id \
         WHERE u.private_key_pem LIKE '-----BEGIN%' LIMIT 1",
    )
    .fetch_optional(&state.db)
    .await?;
    Ok(row.map(|r| {
        let key_id = format!(
            "{}/users/{}#main-key",
            state.config.server_url(),
            r.username
        );
        (key_id, r.private_key_pem)
    }))
}

/// `app.utils.network.is_safe_url`はhttp/httpsを無条件に両方許容するが、
/// ここではHTTP Signature(private keyそのものではないが、身元を証明する
/// 署名材料)を平文HTTPで送信してしまう経路を本番で塞ぐ、Python版より
/// 安全側の意図的な差分にする(CodeQLの"cleartext transmission of sensitive
/// information"指摘への対応、かつ`resolve_webfinger`の
/// "M-13: 本番環境ではHTTPフォールバックを無効化"と同じ既存方針の適用)。
/// `allow_private_networks`(テスト/開発環境)では従来通りHTTPも許容する。
fn is_acceptable_fetch_scheme(scheme: &str, allow_private_networks: bool) -> bool {
    scheme == "https" || (allow_private_networks && scheme == "http")
}

/// `app.services.actor_service._signed_get` を移植したもの。リダイレクトを
/// 手動で追跡し、各ホップでSSRF検証 + 署名し直す(Hostが変わるため)。
/// 本文が要らないGET専用。
async fn signed_get(state: &AppState, start_url: &str) -> Option<(u16, String)> {
    // ローカルユーザーが1人もいない(セットアップ前)場合、Python版は署名なしで
    // フェッチを続行する(`headers_for`が`signing`がNoneならSignatureヘッダーを
    // 付けないだけ)。
    let signing = get_signing_key(state).await.ok().flatten();

    let mut current = start_url.to_string();
    for _ in 0..=MAX_REDIRECTS {
        let parsed = reqwest::Url::parse(&current).ok()?;
        if !is_acceptable_fetch_scheme(parsed.scheme(), state.config.allow_private_networks) {
            return None;
        }
        let host = parsed.host_str()?;
        if !state.config.allow_private_networks && is_host_blocked(host).await {
            return None;
        }

        let client = build_client_for(&parsed, state.config.allow_private_networks)
            .await
            .ok()?;

        let mut request = client.get(current.as_str()).header("Accept", AP_ACCEPT);
        if let Some((key_id, private_key_pem)) = &signing {
            if let Some(headers) =
                sign_request(private_key_pem, key_id, "GET", current.as_str(), None)
            {
                for (name, value) in headers {
                    // Hostは reqwest がURLから自動設定するため上書きしない
                    // (二重ヘッダーになるのを避ける)。
                    if name.eq_ignore_ascii_case("host") {
                        continue;
                    }
                    request = request.header(name, value);
                }
            }
        }

        let resp = request.send().await.ok()?;
        let status = resp.status();

        if matches!(status.as_u16(), 301 | 302 | 303 | 307 | 308) {
            let location = resp
                .headers()
                .get(reqwest::header::LOCATION)?
                .to_str()
                .ok()?;
            let resolved = parsed.join(location).ok()?;
            if !is_acceptable_fetch_scheme(resolved.scheme(), state.config.allow_private_networks) {
                return None;
            }
            current = resolved.to_string();
            continue;
        }

        let body = resp.text().await.ok()?;
        return Some((status.as_u16(), body));
    }
    None
}

/// `app.services.actor_service.get_actor_by_ap_id` 相当。
async fn fetch_actor_row(db: &PgPool, ap_id: &str) -> Result<Option<FullActorRow>, AppError> {
    let row = sqlx::query_as::<_, FullActorRow>(
        r#"
        SELECT id, ap_id, type, username, domain, display_name, summary, avatar_url,
               header_url, inbox_url, outbox_url, shared_inbox_url, followers_url,
               following_url, public_key_pem, public_key_ed25519_multibase, key_id_ed25519,
               is_cat, is_bot, require_signin_to_view, make_notes_followers_only_before,
               make_notes_hidden_before, manually_approves_followers, discoverable, fields,
               birthday, last_fetched_at, featured_url, moved_to_ap_id, also_known_as, deleted_at
        FROM actors WHERE ap_id = $1
        "#,
    )
    .bind(ap_id)
    .fetch_optional(db)
    .await?;
    Ok(row)
}

/// `actors`テーブルの全カラムに対応する行。`get_actor_public_key`に加えて
/// `inbox.rs`のFollow/Block/Delete/Flag/Undoハンドラーがactorのdomain/
/// inbox_url/manually_approves_followers等を広く読む。一部フィールド
/// (例: `birthday`)は現時点でどの呼び出し元も読まないが、この構造体自体は
/// `upsert_remote_actor`が書き込む値の正しさを表明する意味を持つため
/// `#[allow(dead_code)]`で保持する(未使用フィールド警告の抑制目的の
/// プレースホルダーではない)。
#[derive(sqlx::FromRow, Clone)]
#[allow(dead_code)]
pub struct FullActorRow {
    pub id: Uuid,
    pub ap_id: String,
    #[sqlx(rename = "type")]
    pub actor_type: String,
    pub username: String,
    pub domain: Option<String>,
    pub display_name: Option<String>,
    pub summary: Option<String>,
    pub avatar_url: Option<String>,
    pub header_url: Option<String>,
    pub inbox_url: String,
    pub outbox_url: Option<String>,
    pub shared_inbox_url: Option<String>,
    pub followers_url: Option<String>,
    pub following_url: Option<String>,
    pub public_key_pem: String,
    pub public_key_ed25519_multibase: Option<String>,
    pub key_id_ed25519: Option<String>,
    pub is_cat: bool,
    pub is_bot: bool,
    pub require_signin_to_view: bool,
    pub make_notes_followers_only_before: Option<i64>,
    pub make_notes_hidden_before: Option<i64>,
    pub manually_approves_followers: bool,
    pub discoverable: bool,
    pub fields: Option<Value>,
    pub birthday: Option<chrono::NaiveDate>,
    pub last_fetched_at: Option<DateTime<Utc>>,
    pub featured_url: Option<String>,
    pub moved_to_ap_id: Option<String>,
    pub also_known_as: Option<Value>,
    pub deleted_at: Option<DateTime<Utc>>,
}

fn truthy_str(v: Option<&Value>) -> Option<String> {
    v.and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .map(str::to_string)
}

/// FEP-521a Multikey: `assertionMethod`/`verificationMethod` からEd25519公開鍵
/// (`z6Mk`で始まるmultibase文字列)を抽出する。
/// `app.services.actor_service.upsert_remote_actor` の該当箇所を移植したもの。
fn extract_ed25519_multikey(data: &Value) -> (Option<String>, Option<String>) {
    for field in ["assertionMethod", "verificationMethod"] {
        let Some(method_value) = data.get(field) else {
            continue;
        };
        let candidates: Vec<&Value> = match method_value {
            Value::Array(arr) => arr.iter().collect(),
            other => vec![other],
        };
        for cand in candidates {
            let Some(obj) = cand.as_object() else {
                continue;
            };
            if obj.get("type").and_then(Value::as_str) != Some("Multikey") {
                continue;
            }
            if let Some(mb) = obj.get("publicKeyMultibase").and_then(Value::as_str) {
                if mb.starts_with("z6Mk") {
                    let key_id = obj.get("id").and_then(Value::as_str).map(str::to_string);
                    return (Some(mb.to_string()), key_id);
                }
            }
        }
    }
    (None, None)
}

/// `attachment`配列のPropertyValue型からプロフィールフィールドを抽出する。
fn extract_fields(data: &Value) -> Option<Vec<Value>> {
    let attachments = data.get("attachment")?.as_array()?;
    Some(
        attachments
            .iter()
            .filter_map(|att| {
                let obj = att.as_object()?;
                if obj.get("type").and_then(Value::as_str) != Some("PropertyValue") {
                    return None;
                }
                let name = obj.get("name").and_then(Value::as_str).unwrap_or("");
                let value = obj.get("value").and_then(Value::as_str).unwrap_or("");
                Some(serde_json::json!({
                    "name": nekonoverse_core::sanitize::sanitize_html(name),
                    "value": nekonoverse_core::sanitize::sanitize_html(value),
                }))
            })
            .collect(),
    )
}

/// カスタム絵文字の`tag`配列を処理し、`custom_emojis`にupsertする。
/// `app.services.actor_service.upsert_remote_actor`のtagループ相当。
async fn upsert_emoji_tags(
    db: &PgPool,
    data: &Value,
    domain: Option<&str>,
) -> Result<(), AppError> {
    let Some(domain) = domain else { return Ok(()) };
    let tags = match data.get("tag") {
        Some(Value::Array(arr)) => arr.clone(),
        Some(obj @ Value::Object(_)) => vec![obj.clone()],
        _ => return Ok(()),
    };
    for tag in &tags {
        let Some(obj) = tag.as_object() else { continue };
        if obj.get("type").and_then(Value::as_str) != Some("Emoji") {
            continue;
        }
        let icon = obj.get("icon");
        let Some(emoji_url) = icon.and_then(|i| i.get("url")).and_then(Value::as_str) else {
            continue;
        };
        let shortcode = obj
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim_matches(':');
        if shortcode.is_empty() {
            continue;
        }
        let static_url = icon
            .and_then(|i| i.get("staticUrl"))
            .and_then(Value::as_str);
        let license = obj.get("license").and_then(Value::as_str).or_else(|| {
            obj.get("_misskey_license")
                .and_then(|l| l.get("freeText"))
                .and_then(Value::as_str)
        });
        let is_sensitive = obj
            .get("isSensitive")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        let author = obj.get("author").and_then(Value::as_str);
        let description = obj.get("description").and_then(Value::as_str);
        let copy_permission = obj.get("copyPermission").and_then(Value::as_str);
        let usage_info = obj.get("usageInfo").and_then(Value::as_str);
        let is_based_on = obj.get("isBasedOn").and_then(Value::as_str);
        let category = obj.get("category").and_then(Value::as_str);
        let aliases = obj.get("keywords").cloned();

        sqlx::query(
            r#"
            INSERT INTO custom_emojis (
                id, shortcode, domain, url, static_url, visible_in_picker, aliases, license,
                is_sensitive, author, description, copy_permission, usage_info, is_based_on,
                category, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, false, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $15)
            ON CONFLICT (shortcode, domain) DO UPDATE SET
                url = EXCLUDED.url,
                static_url = COALESCE(NULLIF(EXCLUDED.static_url, ''), custom_emojis.static_url),
                aliases = COALESCE(EXCLUDED.aliases, custom_emojis.aliases),
                license = COALESCE(NULLIF(EXCLUDED.license, ''), custom_emojis.license),
                is_sensitive = EXCLUDED.is_sensitive,
                author = COALESCE(NULLIF(EXCLUDED.author, ''), custom_emojis.author),
                description = COALESCE(NULLIF(EXCLUDED.description, ''), custom_emojis.description),
                copy_permission = COALESCE(NULLIF(EXCLUDED.copy_permission, ''), custom_emojis.copy_permission),
                usage_info = COALESCE(NULLIF(EXCLUDED.usage_info, ''), custom_emojis.usage_info),
                is_based_on = COALESCE(NULLIF(EXCLUDED.is_based_on, ''), custom_emojis.is_based_on),
                category = COALESCE(NULLIF(EXCLUDED.category, ''), custom_emojis.category),
                updated_at = EXCLUDED.updated_at
            "#,
        )
        .bind(crate::db::new_id())
        .bind(shortcode)
        .bind(domain)
        .bind(emoji_url)
        .bind(static_url)
        .bind(aliases)
        .bind(license)
        .bind(is_sensitive)
        .bind(author)
        .bind(description)
        .bind(copy_permission)
        .bind(usage_info)
        .bind(is_based_on)
        .bind(category)
        .bind(crate::db::now())
        .execute(db)
        .await?;
    }
    Ok(())
}

/// `app.services.actor_service.upsert_remote_actor` を移植したもの。
pub async fn upsert_remote_actor(
    state: &AppState,
    data: &Value,
) -> Result<Option<FullActorRow>, AppError> {
    let Some(ap_id) = data.get("id").and_then(Value::as_str) else {
        return Ok(None);
    };
    let Some(username) = truthy_str(data.get("preferredUsername")) else {
        return Ok(None);
    };

    let domain = reqwest::Url::parse(ap_id)
        .ok()
        .and_then(|u| u.host_str().map(str::to_string));

    let public_key_pem = data
        .get("publicKey")
        .and_then(|pk| pk.get("publicKeyPem"))
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();

    let (ed25519_multibase, ed25519_key_id) = extract_ed25519_multikey(data);

    let shared_inbox = data
        .get("endpoints")
        .and_then(|e| e.get("sharedInbox"))
        .and_then(Value::as_str)
        .map(str::to_string);

    let actor_type = data
        .get("type")
        .and_then(Value::as_str)
        .unwrap_or("Person")
        .to_string();
    let is_bot = actor_type == "Service";

    let fields = extract_fields(data);

    let birthday = data
        .get("vcard:bday")
        .and_then(Value::as_str)
        .and_then(|s| chrono::NaiveDate::parse_from_str(s, "%Y-%m-%d").ok());

    upsert_emoji_tags(&state.db, data, domain.as_deref()).await?;

    let existing = fetch_actor_row(&state.db, ap_id).await?;
    let now = crate::db::now();

    if let Some(existing) = existing {
        let display_name = truthy_str(data.get("name")).unwrap_or_else(|| username.clone());
        let summary =
            truthy_str(data.get("summary")).map(|s| nekonoverse_core::sanitize::sanitize_html(&s));
        // `data.get("inbox", existing.inbox_url)`: キーが存在しない場合のみ既存値を保持。
        let inbox_url = data
            .get("inbox")
            .and_then(Value::as_str)
            .map(str::to_string)
            .unwrap_or(existing.inbox_url);
        let outbox_url = if data.get("outbox").is_some() {
            data.get("outbox")
                .and_then(Value::as_str)
                .map(str::to_string)
        } else {
            existing.outbox_url
        };
        let shared_inbox_url = shared_inbox.or(existing.shared_inbox_url);
        let followers_url = data
            .get("followers")
            .and_then(Value::as_str)
            .map(str::to_string);
        let following_url = data
            .get("following")
            .and_then(Value::as_str)
            .map(str::to_string);
        let final_public_key_pem = if public_key_pem.is_empty() {
            existing.public_key_pem
        } else {
            public_key_pem
        };
        let avatar_url = match data.get("icon").and_then(Value::as_object) {
            Some(icon) => icon.get("url").and_then(Value::as_str).map(str::to_string),
            None => existing.avatar_url,
        };
        let header_url = match data.get("image").and_then(Value::as_object) {
            Some(image) => image.get("url").and_then(Value::as_str).map(str::to_string),
            None => existing.header_url,
        };
        let is_cat = data.get("isCat").and_then(Value::as_bool).unwrap_or(false);
        let require_signin_to_view = data
            .get("_misskey_requireSigninToViewContents")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        let make_notes_followers_only_before = data
            .get("_misskey_makeNotesFollowersOnlyBefore")
            .and_then(Value::as_i64);
        let make_notes_hidden_before = data
            .get("_misskey_makeNotesHiddenBefore")
            .and_then(Value::as_i64);
        let manually_approves_followers = data
            .get("manuallyApprovesFollowers")
            .and_then(Value::as_bool)
            .unwrap_or(existing.manually_approves_followers);
        let discoverable = data
            .get("discoverable")
            .and_then(Value::as_bool)
            .unwrap_or(existing.discoverable);
        let final_fields = match fields {
            Some(f) => Some(Value::Array(f)),
            None => existing.fields,
        };
        let featured_url = data
            .get("featured")
            .and_then(Value::as_str)
            .map(str::to_string);
        let moved_to_ap_id = data
            .get("movedTo")
            .and_then(Value::as_str)
            .map(str::to_string);
        let also_known_as = match data.get("alsoKnownAs").and_then(Value::as_array) {
            Some(aka) => Some(Value::Array(aka.clone())),
            None => existing.also_known_as,
        };

        sqlx::query(
            r#"
            UPDATE actors SET
                type = $1, display_name = $2, summary = $3, inbox_url = $4, outbox_url = $5,
                shared_inbox_url = $6, followers_url = $7, following_url = $8,
                public_key_pem = $9, public_key_ed25519_multibase = $10, key_id_ed25519 = $11,
                last_fetched_at = $12, avatar_url = $13, header_url = $14, is_cat = $15,
                is_bot = $16, require_signin_to_view = $17,
                make_notes_followers_only_before = $18, make_notes_hidden_before = $19,
                manually_approves_followers = $20, discoverable = $21, fields = $22,
                birthday = $23, featured_url = $24, moved_to_ap_id = $25, also_known_as = $26,
                updated_at = $27
            WHERE id = $28
            "#,
        )
        .bind(&actor_type)
        .bind(&display_name)
        .bind(&summary)
        .bind(&inbox_url)
        .bind(&outbox_url)
        .bind(&shared_inbox_url)
        .bind(&followers_url)
        .bind(&following_url)
        .bind(&final_public_key_pem)
        .bind(&ed25519_multibase)
        .bind(&ed25519_key_id)
        .bind(now)
        .bind(&avatar_url)
        .bind(&header_url)
        .bind(is_cat)
        .bind(is_bot)
        .bind(require_signin_to_view)
        .bind(make_notes_followers_only_before)
        .bind(make_notes_hidden_before)
        .bind(manually_approves_followers)
        .bind(discoverable)
        .bind(&final_fields)
        .bind(birthday)
        .bind(&featured_url)
        .bind(&moved_to_ap_id)
        .bind(&also_known_as)
        .bind(now)
        .bind(existing.id)
        .execute(&state.db)
        .await?;

        return Ok(Some(FullActorRow {
            id: existing.id,
            ap_id: existing.ap_id,
            actor_type,
            username: existing.username,
            domain: existing.domain,
            display_name: Some(display_name),
            summary,
            avatar_url,
            header_url,
            inbox_url,
            outbox_url,
            shared_inbox_url,
            followers_url,
            following_url,
            public_key_pem: final_public_key_pem,
            public_key_ed25519_multibase: ed25519_multibase,
            key_id_ed25519: ed25519_key_id,
            is_cat,
            is_bot,
            require_signin_to_view,
            make_notes_followers_only_before,
            make_notes_hidden_before,
            manually_approves_followers,
            discoverable,
            fields: final_fields,
            birthday,
            last_fetched_at: Some(now),
            featured_url,
            moved_to_ap_id,
            also_known_as,
            deleted_at: existing.deleted_at,
        }));
    }

    // 新規作成パス
    let avatar_url = data
        .get("icon")
        .and_then(Value::as_object)
        .and_then(|icon| icon.get("url"))
        .and_then(Value::as_str)
        .map(str::to_string);
    let header_url = data
        .get("image")
        .and_then(Value::as_object)
        .and_then(|image| image.get("url"))
        .and_then(Value::as_str)
        .map(str::to_string);
    let display_name = truthy_str(data.get("name")).unwrap_or_else(|| username.clone());
    let summary =
        truthy_str(data.get("summary")).map(|s| nekonoverse_core::sanitize::sanitize_html(&s));
    let inbox_url = data
        .get("inbox")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let outbox_url = data
        .get("outbox")
        .and_then(Value::as_str)
        .map(str::to_string);
    let followers_url = data
        .get("followers")
        .and_then(Value::as_str)
        .map(str::to_string);
    let following_url = data
        .get("following")
        .and_then(Value::as_str)
        .map(str::to_string);
    let is_cat = data.get("isCat").and_then(Value::as_bool).unwrap_or(false);
    let require_signin_to_view = data
        .get("_misskey_requireSigninToViewContents")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let make_notes_followers_only_before = data
        .get("_misskey_makeNotesFollowersOnlyBefore")
        .and_then(Value::as_i64);
    let make_notes_hidden_before = data
        .get("_misskey_makeNotesHiddenBefore")
        .and_then(Value::as_i64);
    let manually_approves_followers = data
        .get("manuallyApprovesFollowers")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let discoverable = data
        .get("discoverable")
        .and_then(Value::as_bool)
        .unwrap_or(true);
    let final_fields = Value::Array(fields.unwrap_or_default());
    let featured_url = data
        .get("featured")
        .and_then(Value::as_str)
        .map(str::to_string);
    let moved_to_ap_id = data
        .get("movedTo")
        .and_then(Value::as_str)
        .map(str::to_string);
    let also_known_as = data
        .get("alsoKnownAs")
        .and_then(Value::as_array)
        .map(|a| Value::Array(a.clone()));

    let new_id = crate::db::new_id();
    sqlx::query(
        r#"
        INSERT INTO actors (
            id, ap_id, type, username, domain, display_name, summary, avatar_url, header_url,
            inbox_url, outbox_url, shared_inbox_url, followers_url, following_url,
            public_key_pem, public_key_ed25519_multibase, key_id_ed25519, is_cat, is_bot,
            require_signin_to_view, make_notes_followers_only_before, make_notes_hidden_before,
            manually_approves_followers, discoverable, fields, birthday, last_fetched_at,
            featured_url, moved_to_ap_id, also_known_as, created_at, updated_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19,
            $20, $21, $22, $23, $24, $25, $26, $27, $28, $29, $30, $31, $31
        )
        "#,
    )
    .bind(new_id)
    .bind(ap_id)
    .bind(&actor_type)
    .bind(&username)
    .bind(&domain)
    .bind(&display_name)
    .bind(&summary)
    .bind(&avatar_url)
    .bind(&header_url)
    .bind(&inbox_url)
    .bind(&outbox_url)
    .bind(&shared_inbox)
    .bind(&followers_url)
    .bind(&following_url)
    .bind(&public_key_pem)
    .bind(&ed25519_multibase)
    .bind(&ed25519_key_id)
    .bind(is_cat)
    .bind(is_bot)
    .bind(require_signin_to_view)
    .bind(make_notes_followers_only_before)
    .bind(make_notes_hidden_before)
    .bind(manually_approves_followers)
    .bind(discoverable)
    .bind(&final_fields)
    .bind(birthday)
    .bind(now)
    .bind(&featured_url)
    .bind(&moved_to_ap_id)
    .bind(&also_known_as)
    .bind(now)
    .execute(&state.db)
    .await?;

    Ok(Some(FullActorRow {
        id: new_id,
        ap_id: ap_id.to_string(),
        actor_type,
        username,
        domain,
        display_name: Some(display_name),
        summary,
        avatar_url,
        header_url,
        inbox_url,
        outbox_url,
        shared_inbox_url: shared_inbox,
        followers_url,
        following_url,
        public_key_pem,
        public_key_ed25519_multibase: ed25519_multibase,
        key_id_ed25519: ed25519_key_id,
        is_cat,
        is_bot,
        require_signin_to_view,
        make_notes_followers_only_before,
        make_notes_hidden_before,
        manually_approves_followers,
        discoverable,
        fields: Some(final_fields),
        birthday,
        last_fetched_at: Some(now),
        featured_url,
        moved_to_ap_id,
        also_known_as,
        deleted_at: None,
    }))
}

/// `app.services.actor_service.get_actor_by_ap_id` を移植したもの。ネットワーク
/// フェッチは行わない(既知のactorのローカル解決専用)。inbox受信処理
/// (`inbox.rs`)がactivityの`actor`/`object`フィールドを解決する際、未知の
/// リモートactorへは`fetch_remote_actor`へフォールバックする形で使う。
pub async fn get_actor_by_ap_id(
    state: &AppState,
    ap_id: &str,
) -> Result<Option<FullActorRow>, AppError> {
    if let Some(actor) = fetch_actor_row(&state.db, ap_id).await? {
        return Ok(Some(actor));
    }

    // フォールバック: ap_id がローカルアクターURLの形式であれば、ユーザー名で検索する
    // (保存された ap_id の http/https スキーム不一致に対応)。
    let Ok(parsed) = reqwest::Url::parse(ap_id) else {
        return Ok(None);
    };
    if parsed.host_str() != Some(state.config.domain.as_str()) {
        return Ok(None);
    }
    let Some(username) = parsed.path().strip_prefix("/users/") else {
        return Ok(None);
    };
    let username = username.trim_end_matches('/');
    if username.is_empty() {
        return Ok(None);
    }
    let row: Option<FullActorRow> = sqlx::query_as(
        r#"
        SELECT id, ap_id, type, username, domain, display_name, summary, avatar_url,
               header_url, inbox_url, outbox_url, shared_inbox_url, followers_url,
               following_url, public_key_pem, public_key_ed25519_multibase, key_id_ed25519,
               is_cat, is_bot, require_signin_to_view, make_notes_followers_only_before,
               make_notes_hidden_before, manually_approves_followers, discoverable, fields,
               birthday, last_fetched_at, featured_url, moved_to_ap_id, also_known_as, deleted_at
        FROM actors WHERE username = $1 AND domain IS NULL
        "#,
    )
    .bind(username.to_lowercase())
    .fetch_optional(&state.db)
    .await?;
    Ok(row)
}

/// `app.services.actor_service.fetch_remote_actor` を移植したもの。
pub async fn fetch_remote_actor(
    state: &AppState,
    ap_id: &str,
) -> Result<Option<FullActorRow>, AppError> {
    let existing = fetch_actor_row(&state.db, ap_id).await?;
    if let Some(existing) = &existing {
        if let Some(last_fetched_at) = existing.last_fetched_at {
            if (Utc::now() - last_fetched_at).num_seconds() < CACHE_TTL_SECS {
                return Ok(Some(existing.clone()));
            }
        }
    }

    let Some((status, body)) = signed_get(state, ap_id).await else {
        return Ok(existing);
    };
    if status != 200 {
        return Ok(existing);
    }
    let Ok(data) = serde_json::from_str::<Value>(&body) else {
        return Ok(existing);
    };

    // M-12: リクエストURLとレスポンスのidのドメインが一致するか検証。
    if let Some(response_id) = data.get("id").and_then(Value::as_str) {
        let req_domain = reqwest::Url::parse(ap_id)
            .ok()
            .and_then(|u| u.host_str().map(str::to_string));
        let res_domain = reqwest::Url::parse(response_id)
            .ok()
            .and_then(|u| u.host_str().map(str::to_string));
        if let (Some(req_domain), Some(res_domain)) = (&req_domain, &res_domain) {
            if req_domain != res_domain {
                return Ok(existing);
            }
        }
    }

    upsert_remote_actor(state, &data).await
}

/// `app.services.actor_service.get_actor_public_key` を移植したもの。
pub async fn get_actor_public_key(
    state: &AppState,
    key_id: &str,
) -> Result<Option<ActorKeyInfo>, AppError> {
    let actor_ap_id = key_id.split('#').next().unwrap_or(key_id);
    let Some(actor) = fetch_remote_actor(state, actor_ap_id).await? else {
        return Ok(None);
    };

    if let (Some(mb), Some(kid)) = (&actor.public_key_ed25519_multibase, &actor.key_id_ed25519) {
        if kid == key_id {
            return Ok(Some(ActorKeyInfo {
                actor_id: actor.id,
                public_key_material: mb.clone(),
                algorithm: "ed25519".to_string(),
            }));
        }
    }

    Ok(Some(ActorKeyInfo {
        actor_id: actor.id,
        public_key_material: actor.public_key_pem.clone(),
        algorithm: "rsa-sha256".to_string(),
    }))
}
