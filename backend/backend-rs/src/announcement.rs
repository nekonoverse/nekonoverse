//! `app.services.announcement_service._render_content` を移植したもの。
//! `markdown.markdown(raw, extensions=["tables", "fenced_code"])` で生成した
//! HTMLを`bleach.clean(html, tags=_ALLOWED_TAGS, attributes={"a": ["href"]},
//! strip=True)`でサニタイズするPython版の2段処理を、`pulldown-cmark`
//! (CommonMark + テーブル拡張) + `ammonia`で再現する。
//!
//! 既知の差異(お知らせは信頼済みスタッフのみが作成できるため、
//! `sanitize::sanitize_html`(リモート由来コンテンツ向け)ほど厳密な一致は
//! 求めず、安全側にのみ倒れる差異として許容する):
//! - ネストしたリスト(`- one\n  - nested`)は、Python-Markdown本体が
//!   ネスト判定に4スペースインデントを要求するため2スペースでは
//!   フラットな単一`<ul>`になるが、CommonMark(pulldown-cmark)は
//!   親マーカー幅基準でネストを判定するため2スペースでもネストした
//!   `<ul>`になりうる。
//! - `<script>`/`<style>`を渡した場合、bleachはタグを除去しつつ内部の
//!   テキストは残すが、ammoniaは(`sanitize::sanitize_html`と同じ既知の差異)
//!   タグごと内容も完全に除去する。
//! - フェンスコードブロック内の`"`は、Python-Markdownは(HTML的には不要な)
//!   `&quot;`エスケープを行うが、pulldown-cmarkは非エスケープの生の`"`を
//!   出力する。ブラウザでの表示結果は同一。
//! - テーブルのタグ間改行の入り方が異なる(`<thead>`内は無改行、Python版は
//!   要素ごとに常に改行)が、タグ構造・内容は完全一致でレンダリング結果に
//!   差は無い。

use std::collections::{HashMap, HashSet};

use pulldown_cmark::{html, Options, Parser};

const ALLOWED_TAGS: &[&str] = &[
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "br",
    "hr",
    "strong",
    "em",
    "code",
    "pre",
    "blockquote",
    "ul",
    "ol",
    "li",
    "a",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
];

pub fn render_content(raw: &str) -> String {
    let mut options = Options::empty();
    options.insert(Options::ENABLE_TABLES);
    let parser = Parser::new_ext(raw, options);
    let mut unsafe_html = String::new();
    html::push_html(&mut unsafe_html, parser);
    sanitize(&unsafe_html).trim_end_matches('\n').to_string()
}

fn sanitize(html: &str) -> String {
    let mut builder = ammonia::Builder::default();
    builder.tags(ALLOWED_TAGS.iter().copied().collect::<HashSet<_>>());
    let mut attrs: HashMap<&str, HashSet<&str>> = HashMap::new();
    attrs.insert("a", ["href"].into_iter().collect());
    builder.tag_attributes(attrs);
    builder.generic_attributes(HashSet::new());
    builder.url_schemes(["http", "https", "mailto"].into_iter().collect());
    builder.link_rel(None);
    builder.clean(html).to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    /// `backend/app/services/announcement_service.py`の`_render_content`を
    /// 実際に(markdown 3.10.3 + bleach 6.4.0で)実行して得たオラクル値。
    #[test]
    fn matches_python_oracle_for_common_cases() {
        let cases: &[(&str, &str)] = &[
            ("Hello world", "<p>Hello world</p>"),
            (
                "First paragraph.\n\nSecond paragraph.",
                "<p>First paragraph.</p>\n<p>Second paragraph.</p>",
            ),
            ("# Title\n\nBody text.", "<h1>Title</h1>\n<p>Body text.</p>"),
            (
                "# H1\n## H2\n### H3\n#### H4\n##### H5\n###### H6",
                "<h1>H1</h1>\n<h2>H2</h2>\n<h3>H3</h3>\n<h4>H4</h4>\n<h5>H5</h5>\n<h6>H6</h6>",
            ),
            (
                "This is **bold** and *italic* and `code`.",
                "<p>This is <strong>bold</strong> and <em>italic</em> and <code>code</code>.</p>",
            ),
            (
                "- one\n- two\n- three",
                "<ul>\n<li>one</li>\n<li>two</li>\n<li>three</li>\n</ul>",
            ),
            (
                "1. one\n2. two\n3. three",
                "<ol>\n<li>one</li>\n<li>two</li>\n<li>three</li>\n</ol>",
            ),
            (
                "> quoted text\n> second line",
                "<blockquote>\n<p>quoted text\nsecond line</p>\n</blockquote>",
            ),
            (
                "See [nekonoverse](https://example.com/path?x=1&y=2) for more.",
                "<p>See <a href=\"https://example.com/path?x=1&amp;y=2\">nekonoverse</a> for more.</p>",
            ),
            (
                "[click me](javascript:alert(1))",
                "<p><a>click me</a></p>",
            ),
            (
                // 改行の入り方がPython版(要素ごとに常に改行)と異なるが
                // (`<thead>`内は無改行、`<tbody>`内の行間のみ改行)、
                // タグ構造・内容は完全一致でレンダリング結果に差は無い。
                "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |",
                "<table><thead><tr><th>a</th><th>b</th></tr></thead><tbody>\n<tr><td>1</td><td>2</td></tr>\n<tr><td>3</td><td>4</td></tr>\n</tbody></table>",
            ),
            (
                "above\n\n---\n\nbelow",
                "<p>above</p>\n<hr>\n<p>below</p>",
            ),
            (
                "before ![alt text](https://example.com/x.png) after",
                "<p>before  after</p>",
            ),
            (
                "before <span class=\"x\">span</span> after",
                "<p>before span after</p>",
            ),
            ("", ""),
            ("   \n\n  ", ""),
            (
                "5 < 10 && 10 > 5 \"quoted\" 'single'",
                "<p>5 &lt; 10 &amp;&amp; 10 &gt; 5 \"quoted\" 'single'</p>",
            ),
            (
                "line one  \nline two",
                "<p>line one<br>\nline two</p>",
            ),
            (
                "```rust\nlet x = 1;\n```",
                "<pre><code>let x = 1;\n</code></pre>",
            ),
        ];

        for (input, expected) in cases {
            assert_eq!(render_content(input), *expected, "input: {input:?}");
        }
    }

    /// フェンスコード内の`"`は、Python-Markdownは`&quot;`にエスケープするが
    /// pulldown-cmarkは生の`"`を出力する(モジュールdoc参照)。表示結果は
    /// 同一なので、実際のRust出力をそのまま期待値として固定する。
    #[test]
    fn fenced_code_quote_escaping_differs_cosmetically_from_python() {
        assert_eq!(
            render_content("```\nfn main() {\n    println!(\"hi\");\n}\n```"),
            "<pre><code>fn main() {\n    println!(\"hi\");\n}\n</code></pre>"
        );
    }

    /// 2スペースインデントのネストリストは、Python-Markdown本体では
    /// フラットな単一`<ul>`になるが、CommonMark(pulldown-cmark)は
    /// ネストした`<ul>`と解釈する(モジュールdoc参照)。
    #[test]
    fn nested_list_with_two_space_indent_differs_from_python() {
        assert_eq!(
            render_content("- one\n  - nested one\n  - nested two\n- two"),
            "<ul>\n<li>one\n<ul>\n<li>nested one</li>\n<li>nested two</li>\n</ul>\n</li>\n<li>two</li>\n</ul>"
        );
    }
}
