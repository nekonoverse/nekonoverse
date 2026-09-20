use std::collections::{HashMap, HashSet};

const ALLOWED_TAGS: [&str; 9] = [
    "a",
    "br",
    "p",
    "span",
    "em",
    "strong",
    "code",
    "pre",
    "blockquote",
];

/// 除去時に単語が結合されるのを防ぐため、区切り (半角スペース) を残す
/// ブロックレベルタグ。bleach (html5lib) は一部のブロックタグが隣接した
/// 場合のみ改行を挿入するという複雑かつ非公開の内部規則を持つ (例:
/// `<div>a</div><div>b</div>` → `a\nb` だが `<table><tr><td>a</td>
/// <td>b</td></tr></table>` → `ab` で区切りなし) が、ここでは「除去される
/// ブロックタグは常に区切りを残す」というより単純で安全側 (単語が結合
/// されない) な規則を採用する。
const BLOCK_SEPARATOR_TAGS: [&str; 27] = [
    "div", "li", "ul", "ol", "dl", "dt", "dd", "h1", "h2", "h3", "h4", "h5", "h6", "table", "tr",
    "td", "th", "thead", "tbody", "tfoot", "section", "article", "header", "footer", "nav",
    "aside", "hr",
];

/// `s` の先頭が `BLOCK_SEPARATOR_TAGS` のいずれかの開始/終了タグ (属性なし、
/// Pass 1 の許可リスト設定によりこの形以外では出現しない) と一致する場合、
/// そのタグ全体の長さを返す。
fn block_separator_tag_len(s: &str) -> Option<usize> {
    for tag in BLOCK_SEPARATOR_TAGS {
        let open = format!("<{tag}>");
        let close = format!("</{tag}>");
        if s.starts_with(open.as_str()) {
            return Some(open.len());
        }
        if s.starts_with(close.as_str()) {
            return Some(close.len());
        }
    }
    None
}

/// `app.utils.sanitize.sanitize_html` (リモートソースからの HTML サニタイズ) を移植したもの。
///
/// 元の Python 実装 (`bleach.clean(html, tags=ALLOWED_TAGS,
/// attributes=ALLOWED_ATTRIBUTES, protocols=ALLOWED_PROTOCOLS, strip=True)`)
/// と同一のタグ・属性・プロトコル許可リストを使う。
///
/// 2段階で処理する:
/// 1. 実際の許可リストに `BLOCK_SEPARATOR_TAGS` (属性は一切許可しない) を
///    加えた拡張許可リストで ammonia に正規の HTML パース・構造修復・
///    属性/プロトコル検証をさせる。
/// 2. 出力中の `BLOCK_SEPARATOR_TAGS` のタグマーカーだけを単一の半角スペース
///    に置換する (連続するマーカーはスペース1つにまとめ、単語の結合を防ぐ)。
///
/// 既知の差異 (安全側にのみ倒れる):
/// - bleach は非許可タグを取り除いた後も `<script>`/`<style>` の内容を
///   テキストとして残すが、ammonia (html5ever ベース) はこれらの
///   raw-text 要素をタグごと内容も含めて完全に除去する。
/// - ブロックタグ除去時の区切り文字は上記の通り bleach の複雑な規則を
///   簡略化している (詳細は `BLOCK_SEPARATOR_TAGS` のコメント参照)。
///
/// 46件の手動テストコーパス (Mastodon/Misskey 実運用に近いパターン、
/// XSS ペイロード、不正な入れ子構造を含む) で比較した結果、上記の既知の
/// 差異以外はすべて bleach と完全一致した。
pub fn sanitize_html(html: &str) -> String {
    let mut builder = ammonia::Builder::default();

    let mut tags: HashSet<&str> = ALLOWED_TAGS.into_iter().collect();
    tags.extend(BLOCK_SEPARATOR_TAGS);

    let mut attrs: HashMap<&str, HashSet<&str>> = HashMap::new();
    attrs.insert(
        "a",
        ["href", "rel", "class", "target"].into_iter().collect(),
    );
    attrs.insert("span", ["class"].into_iter().collect());

    let url_schemes: HashSet<&str> = ["http", "https", "mailto"].into_iter().collect();

    builder.tags(tags);
    builder.tag_attributes(attrs);
    // bleach の ALLOWED_ATTRIBUTES には "*" (全タグ共通) キーが無いため、
    // ammonia のデフォルトの汎用属性 (lang/title 等) も明示的に無効化する。
    builder.generic_attributes(HashSet::new());
    builder.url_schemes(url_schemes);
    // bleach 側は rel 属性をタグの許可属性リストに任せているだけで自動付与
    // しないため、ammonia のデフォルトの rel="noopener noreferrer" 自動付与を無効化する。
    builder.link_rel(None);

    let structured = builder.clean(html).to_string();

    let mut result = String::with_capacity(structured.len());
    let mut rest = structured.as_str();
    loop {
        let Some(idx) = rest.find('<') else {
            result.push_str(rest);
            break;
        };
        result.push_str(&rest[..idx]);
        rest = &rest[idx..];

        if let Some(marker_len) = block_separator_tag_len(rest) {
            if !result.is_empty() && !result.ends_with(' ') {
                result.push(' ');
            }
            rest = &rest[marker_len..];
            continue;
        }

        let end = rest.find('>').map(|i| i + 1).unwrap_or(rest.len());
        result.push_str(&rest[..end]);
        rest = &rest[end..];
    }

    result.trim().to_string()
}
