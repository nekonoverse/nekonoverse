//! `app.services.hashtag_service` の `extract_hashtags`/`upsert_hashtags` を
//! 移植したもの。

use sqlx::PgPool;
use uuid::Uuid;

use crate::db;
use crate::error::AppError;

/// `_HASHTAG_RE = re.compile(r"#([a-zA-Z0-9_ぁ-鿿゠-ヿｦ-ﾟ]+)")` の
/// 文字クラス判定部分。ASCII英数字/アンダースコア + 日本語文字
/// (ひらがな〜CJK統合漢字を覆う大まかな範囲、カタカナ、半角カナ)。
fn is_hashtag_char(c: char) -> bool {
    if c.is_ascii_alphanumeric() || c == '_' {
        return true;
    }
    let cp = c as u32;
    (0x3041..=0x9fff).contains(&cp)
        || (0x30a0..=0x30ff).contains(&cp)
        || (0xff66..=0xff9f).contains(&cp)
}

/// `app.services.hashtag_service.extract_hashtags` を移植したもの。
/// テキストからハッシュタグ名を抽出し、小文字化して重複排除する
/// (初出順を保持)。
pub fn extract_hashtags(text: &str) -> Vec<String> {
    let mut seen = std::collections::HashSet::new();
    let mut result = Vec::new();
    let chars: Vec<char> = text.chars().collect();
    let mut i = 0;
    while i < chars.len() {
        if chars[i] == '#' {
            let mut j = i + 1;
            while j < chars.len() && is_hashtag_char(chars[j]) {
                j += 1;
            }
            if j > i + 1 {
                let tag: String = chars[i + 1..j].iter().collect::<String>().to_lowercase();
                if seen.insert(tag.clone()) {
                    result.push(tag);
                }
                i = j;
                continue;
            }
        }
        i += 1;
    }
    result
}

/// `app.services.hashtag_service.upsert_hashtags` を移植したもの。
/// Python版はハッシュタグの一括SELECT→存在しないものだけINSERTだが、
/// `hashtags.name` に一意制約があるため `INSERT ... ON CONFLICT` による
/// アトミックなupsertに置き換える (bookmark作成のSELECT-then-INSERT→
/// UNIQUE制約捕捉と同じ改善方針、#1145参照)。
pub async fn upsert_hashtags(
    db: &PgPool,
    note_id: Uuid,
    hashtag_names: &[String],
) -> Result<(), AppError> {
    for name in hashtag_names {
        let now = db::now();
        let hashtag_id: Uuid = sqlx::query_scalar(
            "INSERT INTO hashtags (id, name, usage_count, last_used_at) VALUES ($1, $2, 1, $3) \
             ON CONFLICT (name) DO UPDATE SET usage_count = hashtags.usage_count + 1, last_used_at = $3 \
             RETURNING id",
        )
        .bind(db::new_id())
        .bind(name)
        .bind(now)
        .fetch_one(db)
        .await?;

        sqlx::query("INSERT INTO note_hashtags (note_id, hashtag_id) VALUES ($1, $2) ON CONFLICT DO NOTHING")
            .bind(note_id)
            .bind(hashtag_id)
            .execute(db)
            .await?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extracts_ascii_and_japanese_tags() {
        let tags = extract_hashtags("#cats and #猫 and #ネコ");
        assert_eq!(
            tags,
            vec!["cats".to_string(), "猫".to_string(), "ネコ".to_string()]
        );
    }

    #[test]
    fn lowercases_and_dedups_preserving_order() {
        let tags = extract_hashtags("#Cats #dogs #CATS");
        assert_eq!(tags, vec!["cats".to_string(), "dogs".to_string()]);
    }

    #[test]
    fn ignores_bare_hash() {
        assert!(extract_hashtags("just a # sign").is_empty());
    }

    #[test]
    fn no_hashtags() {
        assert!(extract_hashtags("no tags here").is_empty());
    }
}
