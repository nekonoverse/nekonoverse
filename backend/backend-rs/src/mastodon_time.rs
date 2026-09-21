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

/// `app/schemas/note.py` の `NoteEditHistoryEntry.created_at` (`datetime` 型を
/// そのままレスポンスモデルへ渡す唯一のフィールド、他は全て `_to_mastodon_datetime`
/// で手動フォーマットした `str`) が経由する、pydantic v2/FastAPIのデフォルトJSON
/// エンコーダの `datetime.isoformat()` 相当を再現したもの。マイクロ秒が0の場合は
/// 小数部を省略する点が `to_mastodon_datetime`/`iso_z` と異なる。
pub fn to_pydantic_isoformat(dt: DateTime<Utc>) -> String {
    let micros = dt.timestamp_subsec_micros();
    if micros == 0 {
        format!("{}+00:00", dt.format("%Y-%m-%dT%H:%M:%S"))
    } else {
        format!("{}.{:06}+00:00", dt.format("%Y-%m-%dT%H:%M:%S"), micros)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    #[test]
    fn pydantic_isoformat_includes_microseconds_when_nonzero() {
        let dt = Utc.with_ymd_and_hms(2024, 1, 15, 10, 30, 0).unwrap()
            + chrono::Duration::microseconds(123456);
        assert_eq!(
            to_pydantic_isoformat(dt),
            "2024-01-15T10:30:00.123456+00:00"
        );
    }

    #[test]
    fn pydantic_isoformat_omits_fraction_when_zero() {
        let dt = Utc.with_ymd_and_hms(2024, 1, 15, 10, 30, 0).unwrap();
        assert_eq!(to_pydantic_isoformat(dt), "2024-01-15T10:30:00+00:00");
    }
}
