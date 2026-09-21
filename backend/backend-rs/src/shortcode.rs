//! カスタム絵文字ショートコード (`:shortcode:`) 抽出。
//! `app/api/mastodon/accounts.py`/`statuses.py` の `_SHORTCODE_RE =
//! re.compile(r":([a-zA-Z0-9_]+):")` を移植したもの。
//! `routes::accounts`(アカウント表示名等)と `note_response`(投稿本文等)の
//! 両方から使う。

use std::collections::HashSet;

/// `:([a-zA-Z0-9_]+):` の非重複マッチを Python の `re.findall` と同じ規則
/// (貪欲・前の一致の直後から再走査)で抽出する。正規表現クレートを増やす
/// ほどの複雑さではないため手書きする。
pub fn find_shortcodes(text: &str, out: &mut HashSet<String>) {
    let bytes = text.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b':' {
            let start = i + 1;
            let mut j = start;
            while j < bytes.len() && (bytes[j].is_ascii_alphanumeric() || bytes[j] == b'_') {
                j += 1;
            }
            if j > start && j < bytes.len() && bytes[j] == b':' {
                out.insert(text[start..j].to_string());
                i = j + 1;
                continue;
            }
        }
        i += 1;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extracts_multiple_shortcodes() {
        let mut out = HashSet::new();
        find_shortcodes("hello :blobcat: world :party_parrot:", &mut out);
        assert_eq!(
            out,
            HashSet::from(["blobcat".to_string(), "party_parrot".to_string()])
        );
    }

    #[test]
    fn overlapping_colons_do_not_double_match() {
        // Python の re.findall(":([a-zA-Z0-9_]+):", ":a:b:c:") は ["a", "c"] を返す
        // (中間の "b" は前の一致が右側のコロンを消費するため対象外)。
        let mut out = HashSet::new();
        find_shortcodes(":a:b:c:", &mut out);
        assert_eq!(out, HashSet::from(["a".to_string(), "c".to_string()]));
    }

    #[test]
    fn empty_between_colons_is_not_a_match() {
        let mut out = HashSet::new();
        find_shortcodes("::", &mut out);
        assert!(out.is_empty());
    }

    #[test]
    fn no_trailing_colon_is_not_a_match() {
        let mut out = HashSet::new();
        find_shortcodes(":blobcat", &mut out);
        assert!(out.is_empty());
    }
}
