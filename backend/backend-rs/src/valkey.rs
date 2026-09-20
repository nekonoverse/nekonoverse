use redis::aio::ConnectionManager;
use redis::Client;

use crate::config::Config;

pub async fn connect(config: &Config) -> Result<ConnectionManager, redis::RedisError> {
    let client = Client::open(config.valkey_url.as_str())?;
    ConnectionManager::new(client).await
}

/// `app.services.server_settings_service` が使うキャッシュキー規約
/// (`setting:{key}`, 値なしは文字列 `"__NULL__"` で表現) と完全に一致させる。
pub mod settings_cache {
    pub fn cache_key(key: &str) -> String {
        format!("setting:{key}")
    }

    pub const NULL_SENTINEL: &str = "__NULL__";

    /// キャッシュ値 (`mget` の結果) を、値が無いことを示す `__NULL__` センチネルを
    /// `None` に変換しつつ実際の値へデコードする。
    pub fn decode(cached: Option<String>) -> Option<Option<String>> {
        cached.map(|v| if v == NULL_SENTINEL { None } else { Some(v) })
    }
}

/// Pub/Sub チャンネル名規約。`app.pubsub_hub` が使う命名規則と完全に一致させる。
/// Stage 1〜3 ではまだ publish/subscribe しないが、Stage 4 で 1 文字も違えず
/// 踏襲できるよう先に用意しておく。
pub mod channels {
    use uuid::Uuid;

    pub const TIMELINE_PUBLIC: &str = "timeline:public";
    pub const ANNOUNCEMENTS: &str = "announcements";
    pub const EMOJI_UPDATE: &str = "emoji:update";

    pub fn timeline_home(actor_id: Uuid) -> String {
        format!("timeline:home:{actor_id}")
    }

    pub fn timeline_list(list_id: Uuid) -> String {
        format!("timeline:list:{list_id}")
    }

    pub fn notifications(recipient_id: Uuid) -> String {
        format!("notifications:{recipient_id}")
    }
}

/// `{"event": ..., "payload": {...}}` という Pub/Sub メッセージエンベロープ。
/// `app.pubsub_hub` が期待する形式と完全に一致させる。
#[derive(serde::Serialize)]
pub struct Envelope<T: serde::Serialize> {
    pub event: &'static str,
    pub payload: T,
}
