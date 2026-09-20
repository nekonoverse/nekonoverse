use pyo3::prelude::*;
use unicode_general_category::{get_general_category, GeneralCategory};

/// `app.utils.emoji._EMOJI_PATTERN` の文字クラスを移植したもの。
/// 大半の Unicode 絵文字 (Emoji_Presentation, 肌色修飾子, ZWJ シーケンス構成要素) をカバーする。
fn in_emoji_char_class(cp: u32) -> bool {
    matches!(cp,
        0x1F600..=0x1F64F   // Emoticons
        | 0x1F300..=0x1F5FF // Misc Symbols and Pictographs
        | 0x1F680..=0x1F6FF // Transport and Map
        | 0x1F1E0..=0x1F1FF // Flags (Regional Indicator)
        | 0x1F900..=0x1F9FF // Supplemental Symbols and Pictographs
        | 0x1FA00..=0x1FA6F // Chess, Extended-A
        | 0x1FA70..=0x1FAFF // Extended-A cont.
        | 0x1F000..=0x1F02F // Mahjong
        // 肌色修飾子 (0x1F3FB..=0x1F3FF) は上の Misc Symbols and Pictographs
        // (0x1F300..=0x1F5FF) に包含されるため独立した腕を持たない (元の Python
        // 正規表現もこの範囲を重複して記載しているだけで、意味は同一)
        | 0x2600..=0x27B0   // Misc Symbols + Dingbats
        | 0x231A..=0x231B   // Watch/Hourglass
        | 0x23E9..=0x23F3   // Misc technical
        | 0x23F8..=0x23FA   // Misc technical
        | 0x25AA..=0x25AB   // Small squares
        | 0x25B6            // Play
        | 0x25C0            // Reverse
        | 0x25FB..=0x25FE   // Squares
        | 0x2934..=0x2935   // Arrows
        | 0x2B05..=0x2B07   // Arrows
        | 0x2B1B..=0x2B1C   // Squares
        | 0x2B50            // Star
        | 0x2B55            // Circle
        | 0x3030            // Wavy dash
        | 0x303D            // Part alt mark
        | 0x3297            // Circled Ideograph Congratulation
        | 0x3299            // Circled Ideograph Secret
        | 0x200B..=0x200F   // Zero-width chars (incl. ZWJ)
        | 0xFE00..=0xFE0F   // Variation Selectors
        | 0x20E3            // Combining Enclosing Keycap
    )
}

/// `unicodedata.category(char) in ("So", "Sk", "Mn", "Mc", "Cf", "Cn")` と同値。
fn is_emoji_unicode_category(c: char) -> bool {
    matches!(
        get_general_category(c),
        GeneralCategory::OtherSymbol
            | GeneralCategory::ModifierSymbol
            | GeneralCategory::NonspacingMark
            | GeneralCategory::SpacingMark
            | GeneralCategory::Format
            | GeneralCategory::Unassigned
    )
}

/// `app.utils.emoji._is_single_emoji_sequence` を移植したもの。
/// テキストが単一の絵文字シーケンス (ZWJ, 国旗, 肌色修飾子を含む) かどうかを判定する。
fn is_single_emoji_sequence(text: &str) -> bool {
    if text.is_empty() {
        return false;
    }

    // ZWJ を含む場合は合成絵文字 (例: 家族)
    if text.contains('\u{200d}') {
        return true;
    }

    let chars: Vec<char> = text.chars().collect();
    let mut count = 0usize;
    let mut i = 0usize;
    while i < chars.len() {
        let cp = chars[i] as u32;

        // バリエーションセレクタとその他の修飾子をスキップ
        if cp == 0xFE0F || cp == 0xFE0E || cp == 0x20E3 || (0x200B..=0x200F).contains(&cp) {
            i += 1;
            continue;
        }
        // 肌色修飾子
        if (0x1F3FB..=0x1F3FF).contains(&cp) {
            i += 1;
            continue;
        }
        // 地域指標子は国旗のためペアで出現する
        if (0x1F1E0..=0x1F1FF).contains(&cp) {
            if let Some(&next) = chars.get(i + 1) {
                let next_cp = next as u32;
                if (0x1F1E0..=0x1F1FF).contains(&next_cp) {
                    count += 1;
                    i += 2;
                    continue;
                }
            }
        }
        count += 1;
        i += 1;
    }
    count == 1
}

/// `app.utils.emoji.is_single_emoji` を移植したもの。
/// 文字列が単一の絵文字 (ZWJ による合成を含む) かチェックする。
#[pyfunction]
pub fn is_single_emoji(text: &str) -> bool {
    if text.is_empty() || text.chars().count() > 20 {
        return false;
    }

    let trimmed = text.trim();
    if trimmed.is_empty() {
        return false;
    }

    // 一般的な絵文字にはパターンを使用
    if trimmed.chars().all(|c| in_emoji_char_class(c as u32)) {
        return is_single_emoji_sequence(trimmed);
    }

    // フォールバック: すべての文字が絵文字カテゴリかチェック
    if !trimmed.chars().all(is_emoji_unicode_category) {
        return false;
    }

    is_single_emoji_sequence(trimmed)
}
