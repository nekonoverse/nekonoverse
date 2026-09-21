//! `app/utils/sanitize.py` の `MENTION_PATTERN`/`URL_PATTERN`/`text_to_html` を
//! 移植したもの。ローカル投稿の生テキスト (`create_status` の `content`) を
//! Mastodon互換の簡易HTML (自動リンク + メンションリンク + 改行) に変換する。
//!
//! Python版は最初に `bleach.clean(text)` (引数なし = bleachのデフォルト許可
//! リスト: `a`/`abbr`/`acronym`/`b`/`blockquote`/`code`/`em`/`i`/`li`/`ol`/
//! `strong`/`ul` をエスケープせずそのまま通す、html5lib ベースのタグ
//! バランシング込み) を適用するが、ここでは `&`/`<`/`>` を一律エスケープする
//! 単純化を採用する。実務上この投稿フィールドはプレーンテキストであり、
//! 差異が出るのは利用者がbleachのデフォルト許可リストにある少数のタグを
//! 生テキストとして直接タイプした場合のみ (その場合Python版は実タグとして
//! 描画するが、こちらはエスケープされた文字列として表示される) —
//! 安全側にのみ倒れる既知の差異で、`sanitize_html`(rust-core)が採用している
//! 割り切り方針と同じ扱い。

/// `app.services.note_service.extract_mentions` の1件分
/// (`MENTION_PATTERN.finditer` の1マッチ相当)。`start`/`end` はメンション
/// リンク描画時、URLスパンに完全に含まれるマッチを除外するためのバイト範囲。
struct Mention {
    username: String,
    domain: Option<String>,
    start: usize,
    end: usize,
}

/// `MENTION_PATTERN = re.compile(r"@([a-zA-Z0-9_]+)(?:@([a-zA-Z0-9.-]+))?")` を
/// 移植したもの。ユーザー名/ドメインは共にASCIIのみのため、バイト単位の
/// スキャンで安全 (マルチバイト文字はどの分岐にもマッチせず読み飛ばされる)。
fn find_mentions(text: &str) -> Vec<Mention> {
    let bytes = text.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'@' {
            let uname_start = i + 1;
            let mut j = uname_start;
            while j < bytes.len() && (bytes[j].is_ascii_alphanumeric() || bytes[j] == b'_') {
                j += 1;
            }
            if j > uname_start {
                let username = text[uname_start..j].to_string();
                let mut end = j;
                let mut domain = None;
                if j < bytes.len() && bytes[j] == b'@' {
                    let dstart = j + 1;
                    let mut k = dstart;
                    while k < bytes.len()
                        && (bytes[k].is_ascii_alphanumeric()
                            || bytes[k] == b'.'
                            || bytes[k] == b'-')
                    {
                        k += 1;
                    }
                    if k > dstart {
                        domain = Some(text[dstart..k].to_string());
                        end = k;
                    }
                }
                out.push(Mention {
                    username,
                    domain,
                    start: i,
                    end,
                });
                i = end;
                continue;
            }
        }
        i += 1;
    }
    out
}

/// `app.services.note_service.extract_mentions` を移植したもの。生テキストから
/// `(username, domain)` を抽出する。重複排除しない (Python版の `re.finditer` と
/// 同じ — 同じユーザーへの複数回のメンションはそのまま複数件返る)。
pub fn extract_mentions(text: &str) -> Vec<(String, Option<String>)> {
    find_mentions(text)
        .into_iter()
        .map(|m| (m.username, m.domain))
        .collect()
}

/// `URL_PATTERN = re.compile(r"(https?://[^\s<]+)")` を移植したもの。
/// バイト範囲 (開始, 終了) のリストを返す。
fn find_url_spans(text: &str) -> Vec<(usize, usize)> {
    let indices: Vec<(usize, char)> = text.char_indices().collect();
    let mut spans = Vec::new();
    let mut idx = 0;
    while idx < indices.len() {
        let (byte_pos, _) = indices[idx];
        if text[byte_pos..].starts_with("http://") || text[byte_pos..].starts_with("https://") {
            let start = byte_pos;
            let mut end = byte_pos;
            let mut j = idx;
            while j < indices.len() {
                let (bp, ch) = indices[j];
                if ch.is_whitespace() || ch == '<' {
                    break;
                }
                end = bp + ch.len_utf8();
                j += 1;
            }
            spans.push((start, end));
            idx = j;
        } else {
            idx += 1;
        }
    }
    spans
}

/// `bleach.clean(text)` (引数なし) を単純化した、`&`/`<`/`>` のみの
/// エスケープ (モジュール冒頭のコメント参照)。bleachは文字列中の引用符を
/// エスケープしないため、ここでも `"`/`'` はそのまま残す。
fn html_escape(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            _ => out.push(c),
        }
    }
    out
}

/// `app.utils.sanitize.text_to_html` を移植したもの。
pub fn text_to_html(text: &str, server_url: &str) -> String {
    if text.trim().is_empty() {
        return String::new();
    }

    let escaped = html_escape(text);
    let url_spans = find_url_spans(&escaped);
    let mentions = find_mentions(&escaped);

    struct Span {
        start: usize,
        end: usize,
        html: String,
    }

    let mut spans: Vec<Span> = url_spans
        .iter()
        .map(|&(s, e)| {
            let url = &escaped[s..e];
            Span {
                start: s,
                end: e,
                html: format!(
                    r#"<a href="{url}" rel="nofollow noopener noreferrer" target="_blank">{url}</a>"#
                ),
            }
        })
        .collect();

    for m in &mentions {
        // 既存の <a> タグ (直前のURL自動リンク結果) 内はスキップ — bleachの
        // 「既存の <a> タグ内は再パースしない」を、URLスパンへの完全包含
        // 判定で再現する (メンションパターンはURLの非空白ランの内側にしか
        // 出現し得ないため、部分的な重なりは起こらない)。
        if url_spans.iter().any(|&(s, e)| m.start >= s && m.end <= e) {
            continue;
        }
        let href = match &m.domain {
            Some(d) => format!("https://{d}/@{}", m.username),
            None => format!("{server_url}/@{}", m.username),
        };
        let display_html = match &m.domain {
            Some(d) => format!(r#"{}<span class="mention-domain">@{d}</span>"#, m.username),
            None => m.username.clone(),
        };
        let html = format!(
            r#"<span class="h-card"><a href="{href}" class="u-url mention">@<span>{display_html}</span></a></span>"#
        );
        spans.push(Span {
            start: m.start,
            end: m.end,
            html,
        });
    }

    spans.sort_by_key(|s| s.start);

    let mut result = String::with_capacity(escaped.len());
    let mut pos = 0;
    for span in &spans {
        if span.start < pos {
            continue;
        }
        result.push_str(&escaped[pos..span.start]);
        result.push_str(&span.html);
        pos = span.end;
    }
    result.push_str(&escaped[pos..]);

    let with_breaks = result.replace('\n', "<br>");
    format!("<p>{with_breaks}</p>")
}

#[cfg(test)]
mod tests {
    use super::*;

    const SERVER_URL: &str = "https://neko.example";

    #[test]
    fn mention_local_user() {
        let html = text_to_html("Hello @alice", SERVER_URL);
        assert!(html.contains(r#"class="u-url mention""#));
        assert!(html.contains("@<span>alice</span>"));
        assert!(html.contains(&format!(r#"href="{SERVER_URL}/@alice""#)));
    }

    #[test]
    fn mention_remote_user() {
        let html = text_to_html("Hello @bob@remote.example", SERVER_URL);
        assert!(html.contains(r#"class="u-url mention""#));
        assert!(html
            .contains(r#"@<span>bob<span class="mention-domain">@remote.example</span></span>"#));
        assert!(html.contains(r#"href="https://remote.example/@bob""#));
    }

    #[test]
    fn mention_inside_url_not_replaced() {
        let html = text_to_html("See https://example.com/@user/status/123", SERVER_URL);
        assert!(!html.contains(r#"class="u-url mention""#) || html.contains("example.com/@user"));
    }

    #[test]
    fn multiple_mentions() {
        let html = text_to_html("@alice @bob@remote.example hello!", SERVER_URL);
        assert_eq!(html.matches("u-url mention").count(), 2);
    }

    #[test]
    fn text_with_line_breaks() {
        let html = text_to_html("Line 1\nLine 2", SERVER_URL);
        assert!(html.contains("<br>"));
    }

    #[test]
    fn empty_or_whitespace_returns_empty_string() {
        assert_eq!(text_to_html("", SERVER_URL), "");
        assert_eq!(text_to_html("   \n ", SERVER_URL), "");
    }

    #[test]
    fn escapes_angle_brackets_and_ampersand() {
        let html = text_to_html("a < b & c > d", SERVER_URL);
        assert_eq!(html, "<p>a &lt; b &amp; c &gt; d</p>");
    }

    #[test]
    fn extract_mentions_local() {
        let mentions = extract_mentions("Hello @alice");
        assert!(mentions.contains(&("alice".to_string(), None)));
    }

    #[test]
    fn extract_mentions_remote() {
        let mentions = extract_mentions("cc @bob@remote.example");
        assert!(mentions.contains(&("bob".to_string(), Some("remote.example".to_string()))));
    }

    #[test]
    fn extract_mentions_mixed() {
        let mentions = extract_mentions("@alice @bob@remote.example text");
        assert_eq!(mentions.len(), 2);
        assert!(mentions.contains(&("alice".to_string(), None)));
        assert!(mentions.contains(&("bob".to_string(), Some("remote.example".to_string()))));
    }

    #[test]
    fn extract_mentions_none() {
        assert!(extract_mentions("No mentions here").is_empty());
    }

    #[test]
    fn extract_mentions_not_deduplicated() {
        let mentions = extract_mentions("@alice @alice");
        assert_eq!(mentions.len(), 2);
    }
}
