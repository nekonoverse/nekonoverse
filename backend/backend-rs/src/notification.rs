//! `app/services/notification_service.py` の `create_notification`(通知行の
//! 作成本体)と `publish_notification` を移植したもの。
//!
//! Python版の `create_notification` は、通知行を作成した後にWeb Push配送
//! (VAPID鍵管理を要する)とDiscord互換Webhook配送を行うが、いずれも個別の
//! `try/except`で囲われており失敗しても通知作成自体は成功として扱われる
//! (`except Exception: logger.exception(...)`のみ、呼び出し元へは伝播しない)。
//! つまりPython版自身が「Web Push/Discord配送はベストエフォートで、
//! 落ちてもいい」という契約にしている。この2つはこの移行がまだ触れていない
//! 別個の大きなサブシステム(VAPID鍵管理、Discord Webhook配送)のため、
//! ここでは通知行作成本体(重複排除・ブロック/ミュート確認・INSERT)と
//! `publish_notification`(アプリ内リアルタイム通知用のValkey publish、
//! これも同じくベストエフォート)のみを移植する。この関数を呼ぶ操作
//! (reblog等)は、Web Push/Discord通知が飛ばないという既知の挙動差を許容する。

use sqlx::PgPool;
use uuid::Uuid;

use crate::db;
use crate::error::AppError;
use crate::valkey::{channels, publish_envelope, Envelope};

pub struct NotificationRow {
    pub id: Uuid,
    pub notification_type: String,
    pub recipient_id: Uuid,
}

/// `app.services.notification_service.create_notification` のうち、
/// Web Push/Discord Webhook配送を除く通知行作成本体を移植したもの。
/// 自己通知・ブロック・ミュート・重複の場合は `None` を返す。
pub async fn create_notification(
    db: &PgPool,
    notification_type: &str,
    recipient_id: Uuid,
    sender_id: Option<Uuid>,
    note_id: Option<Uuid>,
    reaction_emoji: Option<&str>,
) -> Result<Option<NotificationRow>, AppError> {
    if let Some(sender_id) = sender_id {
        if recipient_id == sender_id {
            return Ok(None);
        }

        let blocking: bool = sqlx::query_scalar(
            "SELECT EXISTS(SELECT 1 FROM user_blocks WHERE actor_id = $1 AND target_id = $2)",
        )
        .bind(recipient_id)
        .bind(sender_id)
        .fetch_one(db)
        .await?;
        if blocking {
            return Ok(None);
        }

        let muting: bool = sqlx::query_scalar(
            "SELECT EXISTS(SELECT 1 FROM user_mutes WHERE actor_id = $1 AND target_id = $2 \
             AND (expires_at IS NULL OR expires_at > $3))",
        )
        .bind(recipient_id)
        .bind(sender_id)
        .bind(db::now())
        .fetch_one(db)
        .await?;
        if muting {
            return Ok(None);
        }
    }

    // 重複排除。Python版の `dedup_filters` は sender_id/note_id/reaction_emoji が
    // 渡された場合のみそれぞれの条件を追加する(=渡されなければ絞り込まない)。
    // `$n::type IS NULL OR col = $n` はその「条件を追加しない」を再現する。
    let existing: Option<Uuid> = sqlx::query_scalar(
        "SELECT id FROM notifications \
         WHERE type = $1 AND recipient_id = $2 \
           AND ($3::uuid IS NULL OR sender_id = $3) \
           AND ($4::uuid IS NULL OR note_id = $4) \
           AND ($5::text IS NULL OR reaction_emoji = $5) \
         LIMIT 1",
    )
    .bind(notification_type)
    .bind(recipient_id)
    .bind(sender_id)
    .bind(note_id)
    .bind(reaction_emoji)
    .fetch_optional(db)
    .await?;
    if existing.is_some() {
        return Ok(None);
    }

    let id = db::new_id();
    sqlx::query(
        "INSERT INTO notifications \
         (id, type, recipient_id, sender_id, note_id, reaction_emoji, read, created_at) \
         VALUES ($1, $2, $3, $4, $5, $6, false, $7)",
    )
    .bind(id)
    .bind(notification_type)
    .bind(recipient_id)
    .bind(sender_id)
    .bind(note_id)
    .bind(reaction_emoji)
    .bind(db::now())
    .execute(db)
    .await?;

    Ok(Some(NotificationRow {
        id,
        notification_type: notification_type.to_string(),
        recipient_id,
    }))
}

/// `app.services.notification_service.publish_notification` を移植したもの。
pub async fn publish_notification(
    redis: &redis::aio::ConnectionManager,
    notification: &NotificationRow,
) {
    let envelope = Envelope {
        event: "notification",
        payload: serde_json::json!({
            "id": notification.id.to_string(),
            "type": notification.notification_type,
        }),
    };
    publish_envelope(
        redis,
        &channels::notifications(notification.recipient_id),
        &envelope,
    )
    .await;
}
