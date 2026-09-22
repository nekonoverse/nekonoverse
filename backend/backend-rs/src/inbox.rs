//! `app/activitypub/handlers/` のうち Follow/Accept/Reject/Block/Delete/Flag と、
//! `Undo`(Follow/Block サブケースのみ)を移植したもの。`app/activitypub/routes.py`
//! の `process_inbox_activity`(ドメインブロック確認・Valkey冪等性チェック・
//! ハンドラーディスパッチ)もここに同居させる。ルート配線(レート制限・
//! ボディサイズ上限・Digest/HTTP Signature検証・鍵所有者とactivity.actorの
//! 一致検証)は `routes/inbox.rs` 側の責務。
//!
//! `Undo`のLike/EmojiReact/Announceサブケース、および`Create`/`Like`/
//! `EmojiReact`/`Announce`/`Update`/`Move`は、いずれもNote受信基盤(投稿の
//! 新規作成/upsert)がまだ無いため今回のスコープ外。既存の
//! `resolve_webfinger`/`fetch_remote_note`等と同じく、対応するactivity種別が
//! 来てもログのみ出して何もしない優雅な劣化とする(クラッシュや誤ったエラー
//! 応答をしない)。

use serde_json::Value;
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::activitypub::{render_accept_activity, render_reject_activity};
use crate::db;
use crate::delivery::enqueue_delivery;
use crate::domain_block::is_domain_blocked;
use crate::error::AppError;
use crate::notification::{create_notification, publish_notification};
use crate::remote_actor::{fetch_remote_actor, get_actor_by_ap_id, FullActorRow};
use crate::state::AppState;

/// `app.activitypub.routes.process_inbox_activity` の Valkey 冪等性チェック
/// (`seen_activity:*`) と同一の TTL (24時間)。
const SEEN_ACTIVITY_TTL: i64 = 86400;

/// AP の参照 (文字列 or `{"id": ...}`) から ID を取り出す。
/// `app.activitypub.handlers.undo._ap_id_of` を移植したもの。
fn ap_id_of(value: Option<&Value>) -> Option<String> {
    match value? {
        Value::String(s) => Some(s.clone()),
        Value::Object(obj) => obj.get("id").and_then(Value::as_str).map(str::to_string),
        _ => None,
    }
}

async fn resolve_actor_with_fetch(
    state: &AppState,
    ap_id: &str,
) -> Result<Option<FullActorRow>, AppError> {
    if let Some(actor) = get_actor_by_ap_id(state, ap_id).await? {
        return Ok(Some(actor));
    }
    fetch_remote_actor(state, ap_id).await
}

/// `app.activitypub.handlers.follow.handle_follow` を移植したもの。
async fn handle_follow(state: &AppState, activity: &Value) -> Result<(), AppError> {
    let Some(actor_ap_id) = activity.get("actor").and_then(Value::as_str) else {
        return Ok(());
    };
    let Some(target_ap_id) = activity.get("object").and_then(Value::as_str) else {
        return Ok(());
    };

    let Some(follower) = resolve_actor_with_fetch(state, actor_ap_id).await? else {
        tracing::warn!(actor = actor_ap_id, "Could not resolve follower actor");
        return Ok(());
    };

    let Some(target) = get_actor_by_ap_id(state, target_ap_id).await? else {
        tracing::info!(target = target_ap_id, "Follow target is not a local actor");
        return Ok(());
    };
    if target.domain.is_some() {
        tracing::info!(target = target_ap_id, "Follow target is not a local actor");
        return Ok(());
    }

    // ターゲットが送信者をブロックしている場合はFollowを保存せずRejectを返す
    // (instance全体で握りつぶすのではなく宛先ローカルユーザー単位で判定する)。
    let blocking: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM user_blocks WHERE actor_id = $1 AND target_id = $2)",
    )
    .bind(target.id)
    .bind(follower.id)
    .fetch_one(&state.db)
    .await?;
    if blocking {
        let reject_id = format!(
            "{}/activities/{}",
            state.config.server_url(),
            Uuid::new_v4()
        );
        let target_actor_uri = format!("{}/users/{}", state.config.server_url(), target.username);
        let reject = render_reject_activity(&reject_id, &target_actor_uri, activity);
        enqueue_delivery(state, target.id, &follower.inbox_url, &reject).await?;
        tracing::info!(
            actor = actor_ap_id,
            target = target_ap_id,
            "Rejected follow from blocked actor"
        );
        return Ok(());
    }

    let existing: Option<Uuid> =
        sqlx::query_scalar("SELECT id FROM followers WHERE follower_id = $1 AND following_id = $2")
            .bind(follower.id)
            .bind(target.id)
            .fetch_optional(&state.db)
            .await?;

    if existing.is_some() {
        tracing::info!(
            actor = actor_ap_id,
            target = target_ap_id,
            "Follow already exists"
        );
    } else {
        let accepted = !target.manually_approves_followers;
        sqlx::query(
            "INSERT INTO followers (id, ap_id, follower_id, following_id, accepted, created_at) \
             VALUES ($1, $2, $3, $4, $5, $6)",
        )
        .bind(db::new_id())
        .bind(activity.get("id").and_then(Value::as_str))
        .bind(follower.id)
        .bind(target.id)
        .bind(accepted)
        .bind(db::now())
        .execute(&state.db)
        .await?;

        let notif_type = if target.manually_approves_followers {
            "follow_request"
        } else {
            "follow"
        };
        if let Some(notif) = create_notification(
            &state.db,
            notif_type,
            target.id,
            Some(follower.id),
            None,
            None,
        )
        .await?
        {
            publish_notification(&state.redis, &notif).await;
        }
    }

    // 手動承認でない場合は自動承認
    if !target.manually_approves_followers {
        let accept_id = format!(
            "{}/activities/{}",
            state.config.server_url(),
            Uuid::new_v4()
        );
        let actor_uri = format!("{}/users/{}", state.config.server_url(), target.username);
        let accept = render_accept_activity(&accept_id, &actor_uri, activity);
        enqueue_delivery(state, target.id, &follower.inbox_url, &accept).await?;
        tracing::info!(
            actor = actor_ap_id,
            target = target_ap_id,
            "Auto-accepted follow"
        );
    }

    Ok(())
}

#[derive(sqlx::FromRow)]
struct FollowIdRow {
    id: Uuid,
    following_id: Uuid,
}

/// `app.activitypub.handlers.follow._resolve_follow_from_object` を移植したもの。
async fn resolve_follow_from_object(
    state: &AppState,
    activity: &Value,
) -> Result<Option<FollowIdRow>, AppError> {
    let accept_actor = activity.get("actor").and_then(Value::as_str);
    let inner = activity.get("object");

    match inner {
        Some(Value::String(inner_id)) => {
            let Some(accept_actor) = accept_actor else {
                tracing::warn!(
                    inner_id,
                    "Accept/Reject missing actor field for string object"
                );
                return Ok(None);
            };
            let Some(follow): Option<FollowIdRow> =
                sqlx::query_as("SELECT id, following_id FROM followers WHERE ap_id = $1")
                    .bind(inner_id)
                    .fetch_optional(&state.db)
                    .await?
            else {
                tracing::warn!(inner_id, "No follow found for ap_id");
                return Ok(None);
            };
            let Some(target) = get_actor_by_ap_id(state, accept_actor).await? else {
                return Ok(None);
            };
            if target.id != follow.following_id {
                tracing::warn!(accept_actor, "Accept/Reject actor mismatch");
                return Ok(None);
            }
            Ok(Some(follow))
        }
        Some(Value::Object(obj)) => {
            if obj.get("type").and_then(Value::as_str) != Some("Follow") {
                return Ok(None);
            }
            let target_ap_id = obj.get("object").and_then(Value::as_str);
            if let (Some(accept_actor), Some(target_ap_id)) = (accept_actor, target_ap_id) {
                if accept_actor != target_ap_id {
                    tracing::warn!(accept_actor, target_ap_id, "Accept/Reject actor mismatch");
                    return Ok(None);
                }
            }
            let actor_ap_id = obj.get("actor").and_then(Value::as_str);
            let (Some(actor_ap_id), Some(target_ap_id)) = (actor_ap_id, target_ap_id) else {
                return Ok(None);
            };
            let Some(follower) = get_actor_by_ap_id(state, actor_ap_id).await? else {
                return Ok(None);
            };
            let Some(target) = get_actor_by_ap_id(state, target_ap_id).await? else {
                return Ok(None);
            };
            let follow: Option<FollowIdRow> = sqlx::query_as(
                "SELECT id, following_id FROM followers WHERE follower_id = $1 AND following_id = $2",
            )
            .bind(follower.id)
            .bind(target.id)
            .fetch_optional(&state.db)
            .await?;
            Ok(follow)
        }
        _ => Ok(None),
    }
}

/// `app.activitypub.handlers.follow.handle_accept` を移植したもの。
async fn handle_accept(state: &AppState, activity: &Value) -> Result<(), AppError> {
    if let Some(follow) = resolve_follow_from_object(state, activity).await? {
        sqlx::query("UPDATE followers SET accepted = true WHERE id = $1")
            .bind(follow.id)
            .execute(&state.db)
            .await?;
        tracing::info!(follow_id = %follow.id, "Follow accepted");
    }
    Ok(())
}

/// `app.activitypub.handlers.follow.handle_reject` を移植したもの。
async fn handle_reject(state: &AppState, activity: &Value) -> Result<(), AppError> {
    if let Some(follow) = resolve_follow_from_object(state, activity).await? {
        sqlx::query("DELETE FROM followers WHERE id = $1")
            .bind(follow.id)
            .execute(&state.db)
            .await?;
        tracing::info!(follow_id = %follow.id, "Follow rejected");
    }
    Ok(())
}

/// `app.activitypub.handlers.block.handle_block` を移植したもの。
/// Python版は送信者(blocker)を`get_actor_by_ap_id`のみで解決し
/// `fetch_remote_actor`へフォールバックしない(未知のリモートactorからの
/// 初回Blockは無視する、という既存の挙動をそのまま踏襲)。
async fn handle_block(state: &AppState, activity: &Value) -> Result<(), AppError> {
    let Some(actor_ap_id) = activity.get("actor").and_then(Value::as_str) else {
        return Ok(());
    };
    let Some(target_ap_id) = activity.get("object").and_then(Value::as_str) else {
        return Ok(());
    };

    let Some(blocker) = get_actor_by_ap_id(state, actor_ap_id).await? else {
        return Ok(());
    };
    let Some(target) = get_actor_by_ap_id(state, target_ap_id).await? else {
        return Ok(());
    };

    let existing: Option<Uuid> =
        sqlx::query_scalar("SELECT id FROM user_blocks WHERE actor_id = $1 AND target_id = $2")
            .bind(blocker.id)
            .bind(target.id)
            .fetch_optional(&state.db)
            .await?;
    if existing.is_some() {
        return Ok(());
    }

    sqlx::query(
        "INSERT INTO user_blocks (id, actor_id, target_id, created_at) VALUES ($1, $2, $3, $4)",
    )
    .bind(db::new_id())
    .bind(blocker.id)
    .bind(target.id)
    .bind(db::now())
    .execute(&state.db)
    .await?;

    // 双方向のフォローを削除
    sqlx::query(
        "DELETE FROM followers WHERE (follower_id = $1 AND following_id = $2) \
            OR (follower_id = $2 AND following_id = $1)",
    )
    .bind(blocker.id)
    .bind(target.id)
    .execute(&state.db)
    .await?;

    tracing::info!(actor = actor_ap_id, target = target_ap_id, "Block");
    Ok(())
}

/// Delete(Person) 判定に使う AP タイプ。
const PERSON_TYPES: [&str; 5] = ["Person", "Service", "Group", "Organization", "Application"];

#[derive(sqlx::FromRow)]
struct NoteOwnerRow {
    id: Uuid,
    actor_id: Uuid,
}

/// `app.activitypub.handlers.delete.handle_delete` を移植したもの。
async fn handle_delete(state: &AppState, activity: &Value) -> Result<(), AppError> {
    let Some(actor_ap_id) = activity.get("actor").and_then(Value::as_str) else {
        return Ok(());
    };

    let (object_id, object_type): (Option<String>, Option<String>) = match activity.get("object") {
        Some(Value::Object(obj)) => (
            obj.get("id").and_then(Value::as_str).map(str::to_string),
            obj.get("type").and_then(Value::as_str).map(str::to_string),
        ),
        Some(Value::String(s)) => (Some(s.clone()), None),
        _ => return Ok(()),
    };
    let Some(object_id) = object_id else {
        return Ok(());
    };

    // Delete(Person): actor自身の削除、またはオブジェクトがPerson系
    if object_id == actor_ap_id
        || object_type
            .as_deref()
            .is_some_and(|t| PERSON_TYPES.contains(&t))
    {
        return handle_delete_actor(state, actor_ap_id).await;
    }

    let Some(actor) = get_actor_by_ap_id(state, actor_ap_id).await? else {
        return Ok(());
    };

    let note: Option<NoteOwnerRow> =
        sqlx::query_as("SELECT id, actor_id FROM notes WHERE ap_id = $1 AND deleted_at IS NULL")
            .bind(&object_id)
            .fetch_optional(&state.db)
            .await?;
    let Some(note) = note else {
        return Ok(());
    };

    if note.actor_id != actor.id {
        tracing::warn!(actor = actor_ap_id, object = %object_id, "Delete denied: actor does not own note");
        return Ok(());
    }

    sqlx::query("UPDATE notes SET deleted_at = $1 WHERE id = $2")
        .bind(db::now())
        .bind(note.id)
        .execute(&state.db)
        .await?;
    tracing::info!(object = %object_id, actor = actor_ap_id, "Deleted note");

    // 検索インデックスからの削除 (`neko_search_enabled`) はStage 4の
    // Note受信基盤自体が未移植のためスコープ外 (引き続きPython側)。

    Ok(())
}

/// `app.activitypub.handlers.delete._handle_delete_actor` を移植したもの。
/// ローカルアクターの削除はこのハンドラーでは行わない
/// (ローカル削除は account_deletion_service 経由、Python側のまま)。
async fn handle_delete_actor(state: &AppState, actor_ap_id: &str) -> Result<(), AppError> {
    let Some(actor) = get_actor_by_ap_id(state, actor_ap_id).await? else {
        tracing::debug!(actor = actor_ap_id, "Delete(Person) ignored: unknown actor");
        return Ok(());
    };

    if actor.domain.is_none() {
        tracing::warn!(actor = actor_ap_id, "Delete(Person) ignored: local actor");
        return Ok(());
    }
    if actor.deleted_at.is_some() {
        tracing::debug!(
            actor = actor_ap_id,
            "Delete(Person) ignored: already deleted"
        );
        return Ok(());
    }

    let now = db::now();

    sqlx::query("UPDATE notes SET deleted_at = $1 WHERE actor_id = $2 AND deleted_at IS NULL")
        .bind(now)
        .bind(actor.id)
        .execute(&state.db)
        .await?;

    sqlx::query("DELETE FROM followers WHERE follower_id = $1 OR following_id = $1")
        .bind(actor.id)
        .execute(&state.db)
        .await?;

    sqlx::query("DELETE FROM reactions WHERE actor_id = $1")
        .bind(actor.id)
        .execute(&state.db)
        .await?;

    sqlx::query("DELETE FROM notifications WHERE sender_id = $1")
        .bind(actor.id)
        .execute(&state.db)
        .await?;

    sqlx::query(
        "UPDATE actors SET deleted_at = $1, display_name = NULL, summary = NULL, \
            avatar_url = NULL, header_url = NULL WHERE id = $2",
    )
    .bind(now)
    .bind(actor.id)
    .execute(&state.db)
    .await?;

    tracing::info!(
        actor = actor_ap_id,
        "Processed Delete(Person) for remote actor"
    );
    Ok(())
}

/// `app.activitypub.handlers.flag.handle_flag` を移植したもの。
async fn handle_flag(state: &AppState, activity: &Value) -> Result<(), AppError> {
    let Some(actor_ap_id) = activity.get("actor").and_then(Value::as_str) else {
        return Ok(());
    };

    let Some(reporter) = resolve_actor_with_fetch(state, actor_ap_id).await? else {
        tracing::warn!(actor = actor_ap_id, "Could not resolve reporter actor");
        return Ok(());
    };

    let target_ap_ids: Vec<String> = match activity.get("object") {
        Some(Value::String(s)) => vec![s.clone()],
        Some(Value::Array(arr)) => arr
            .iter()
            .filter_map(|v| v.as_str().map(str::to_string))
            .collect(),
        _ => vec![],
    };
    let Some(first_target) = target_ap_ids.first() else {
        return Ok(());
    };

    let Some(target_actor) = get_actor_by_ap_id(state, first_target).await? else {
        tracing::info!(
            target = first_target.as_str(),
            "Flag target actor not found"
        );
        return Ok(());
    };

    let mut target_note_id: Option<Uuid> = None;
    for ap_id in target_ap_ids.iter().skip(1) {
        let note: Option<Uuid> =
            sqlx::query_scalar("SELECT id FROM notes WHERE ap_id = $1 AND deleted_at IS NULL")
                .bind(ap_id)
                .fetch_optional(&state.db)
                .await?;
        if note.is_some() {
            target_note_id = note;
            break;
        }
    }

    let comment = activity
        .get("content")
        .and_then(Value::as_str)
        .unwrap_or("");

    sqlx::query(
        "INSERT INTO reports \
            (id, ap_id, reporter_actor_id, target_actor_id, target_note_id, comment, status, created_at) \
         VALUES ($1, $2, $3, $4, $5, $6, 'open', $7)",
    )
    .bind(db::new_id())
    .bind(activity.get("id").and_then(Value::as_str))
    .bind(reporter.id)
    .bind(target_actor.id)
    .bind(target_note_id)
    .bind(comment)
    .bind(db::now())
    .execute(&state.db)
    .await?;

    tracing::info!(
        actor = actor_ap_id,
        target = first_target.as_str(),
        "Report received"
    );
    Ok(())
}

/// `app.activitypub.handlers.undo._undo_actor` を移植したもの。
/// 取り消し対象の`inner.actor`は送信側が自由に書けるため信用せず、
/// 署名検証済みのactivity.actor(signer)と一致する場合のみ許可する。
fn undo_actor(activity: &Value, inner: &serde_json::Map<String, Value>) -> Option<String> {
    let signer = ap_id_of(activity.get("actor"))?;
    if let Some(inner_actor) = inner.get("actor") {
        if ap_id_of(Some(inner_actor)).as_deref() != Some(signer.as_str()) {
            tracing::warn!(
                ?inner_actor,
                signer,
                "Rejected Undo: inner actor does not match signer"
            );
            return None;
        }
    }
    Some(signer)
}

async fn undo_follow(
    state: &AppState,
    activity: &Value,
    inner: &serde_json::Map<String, Value>,
) -> Result<(), AppError> {
    let Some(actor_ap_id) = undo_actor(activity, inner) else {
        return Ok(());
    };
    let Some(target_ap_id) = ap_id_of(inner.get("object")) else {
        return Ok(());
    };

    let Some(follower) = get_actor_by_ap_id(state, &actor_ap_id).await? else {
        return Ok(());
    };
    let Some(target) = get_actor_by_ap_id(state, &target_ap_id).await? else {
        return Ok(());
    };

    let result = sqlx::query("DELETE FROM followers WHERE follower_id = $1 AND following_id = $2")
        .bind(follower.id)
        .bind(target.id)
        .execute(&state.db)
        .await?;
    if result.rows_affected() > 0 {
        tracing::info!(actor = actor_ap_id, target = target_ap_id, "Undo follow");
    }
    Ok(())
}

async fn undo_block(
    state: &AppState,
    activity: &Value,
    inner: &serde_json::Map<String, Value>,
) -> Result<(), AppError> {
    let Some(actor_ap_id) = undo_actor(activity, inner) else {
        return Ok(());
    };
    let Some(target_ap_id) = ap_id_of(inner.get("object")) else {
        return Ok(());
    };

    let Some(blocker) = get_actor_by_ap_id(state, &actor_ap_id).await? else {
        return Ok(());
    };
    let Some(target) = get_actor_by_ap_id(state, &target_ap_id).await? else {
        return Ok(());
    };

    let result = sqlx::query("DELETE FROM user_blocks WHERE actor_id = $1 AND target_id = $2")
        .bind(blocker.id)
        .bind(target.id)
        .execute(&state.db)
        .await?;
    if result.rows_affected() > 0 {
        tracing::info!(actor = actor_ap_id, target = target_ap_id, "Undo block");
    }
    Ok(())
}

/// `app.activitypub.handlers.undo.handle_undo` を移植したもの。Like/EmojiReact/
/// Announceサブケースはこの移行がまだ持たないNote/Reaction受信基盤を要するため
/// 未移植(モジュールdoc参照)、ログのみ出して優雅に劣化させる。
async fn handle_undo(state: &AppState, activity: &Value) -> Result<(), AppError> {
    let Some(inner) = activity.get("object").and_then(Value::as_object) else {
        return Ok(());
    };

    match inner.get("type").and_then(Value::as_str) {
        Some("Follow") => undo_follow(state, activity, inner).await,
        Some("Block") => undo_block(state, activity, inner).await,
        Some(t @ ("Like" | "EmojiReact" | "Announce")) => {
            tracing::info!(inner_type = t, "Undo not yet supported for this inner type");
            Ok(())
        }
        other => {
            tracing::info!(inner_type = ?other, "Unhandled Undo inner type");
            Ok(())
        }
    }
}

/// `json.dumps(activity, sort_keys=True)` 相当の正規化。`serde_json::Value`の
/// `Object`はデフォルトで`BTreeMap`(キー順序保持機能を有効にしていないため)
/// なので、素直な`to_string`で既にキーがソートされた出力になる。
fn canonical_json(activity: &Value) -> String {
    serde_json::to_string(activity).unwrap_or_default()
}

async fn mark_seen(redis: &mut redis::aio::ConnectionManager, key: &str) -> Result<bool, AppError> {
    let result: Option<String> = redis::cmd("SET")
        .arg(key)
        .arg("1")
        .arg("NX")
        .arg("EX")
        .arg(SEEN_ACTIVITY_TTL)
        .query_async(redis)
        .await?;
    Ok(result.is_some())
}

/// `app.activitypub.routes.process_inbox_activity` を移植したもの。
pub async fn process_inbox_activity(state: &AppState, activity: &Value) -> Result<(), AppError> {
    let activity_type = activity.get("type").and_then(Value::as_str).unwrap_or("");
    let actor_id_str = activity.get("actor").and_then(Value::as_str).unwrap_or("");
    tracing::info!(
        activity_type,
        activity_id = ?activity.get("id"),
        "Processing inbox activity"
    );

    // ドメインブロックチェック
    if !actor_id_str.is_empty() {
        let domain = reqwest::Url::parse(actor_id_str)
            .ok()
            .and_then(|u| u.host_str().map(str::to_string));
        if let Some(domain) = domain {
            if is_domain_blocked(state, &domain).await? {
                tracing::info!(domain, "Rejected activity from blocked domain");
                return Ok(());
            }
        }
    }

    // ユーザーレベルのブロックはここでは判定しない (follow.rs の Reject 送信、
    // notification.rs の通知抑止等、実際の宛先が判明する箇所で個別に判定する。
    // Python版のコメント(M-15)と同じ理由: shared inboxは複数ローカルユーザー宛の
    // 活動を一括で受け取るため、ここで握りつぶすと無関係な宛先まで届かなくなる)。

    // Valkeyによる冪等性チェック
    let mut redis = state.redis.clone();
    let activity_id = activity.get("id").and_then(Value::as_str);
    let is_new = match activity_id {
        Some(id) => {
            // 他アクターが同じIDを先に送って正規の活動を抑止できないよう、署名者ごとに分ける。
            let key = format!("seen_activity:{actor_id_str}:{id}");
            mark_seen(&mut redis, &key).await?
        }
        None => {
            // IDなしの活動はボディハッシュで冪等性チェック
            let body_hash = format!("{:x}", Sha256::digest(canonical_json(activity).as_bytes()));
            let key = format!("seen_activity:hash:{body_hash}");
            mark_seen(&mut redis, &key).await?
        }
    };
    if !is_new {
        tracing::info!("Duplicate activity, skipping");
        return Ok(());
    }

    match activity_type {
        "Follow" => handle_follow(state, activity).await,
        "Accept" => handle_accept(state, activity).await,
        "Reject" => handle_reject(state, activity).await,
        "Undo" => handle_undo(state, activity).await,
        "Delete" => handle_delete(state, activity).await,
        "Flag" => handle_flag(state, activity).await,
        "Block" => handle_block(state, activity).await,
        other => {
            tracing::info!(activity_type = other, "Unhandled activity type");
            Ok(())
        }
    }
}
