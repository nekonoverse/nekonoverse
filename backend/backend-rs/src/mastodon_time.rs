//! `app/api/mastodon/statuses.py` の `_to_mastodon_datetime` を移植したもの。
//! `activitypub::iso_z` (AP用、マイクロ秒精度) とはフォーマットが異なるため
//! 別関数として持つ。`routes::authorized_apps`/`routes::accounts` から使う。

use chrono::{DateTime, Utc};

pub fn to_mastodon_datetime(dt: DateTime<Utc>) -> String {
    format!(
        "{}.{:03}Z",
        dt.format("%Y-%m-%dT%H:%M:%S"),
        dt.timestamp_subsec_millis()
    )
}
