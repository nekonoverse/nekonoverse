import re

from app.utils.sanitize import EMOJI_IMG_RE, sanitize_html, text_to_html


def test_text_to_html_wraps_in_p():
    assert text_to_html("hello") == "<p>hello</p>"


def test_text_to_html_newlines():
    result = text_to_html("line1\nline2")
    assert "<br>" in result


def test_text_to_html_auto_links():
    result = text_to_html("visit https://example.com please")
    assert 'href="https://example.com"' in result
    assert "nofollow" in result


def test_text_to_html_escapes_html():
    result = text_to_html("<script>alert('xss')</script>")
    assert "<script>" not in result


def test_text_to_html_multiple_urls():
    result = text_to_html("https://a.com and https://b.com")
    assert result.count("href=") == 2


def test_text_to_html_plain_text_unchanged():
    result = text_to_html("just plain text")
    assert result == "<p>just plain text</p>"


def test_sanitize_allows_safe_tags():
    html = "<p>hello <strong>world</strong></p>"
    assert sanitize_html(html) == html


def test_sanitize_strips_script():
    html = "<p>hello</p><script>alert(1)</script>"
    assert "<script>" not in sanitize_html(html)


def test_sanitize_strips_onclick():
    html = '<p onclick="alert(1)">hello</p>'
    assert "onclick" not in sanitize_html(html)


def test_sanitize_allows_a_href():
    html = '<a href="https://example.com">link</a>'
    result = sanitize_html(html)
    assert 'href="https://example.com"' in result


def test_sanitize_preserves_target_blank():
    html = '<a href="https://example.com" target="_blank" rel="noopener noreferrer">link</a>'
    result = sanitize_html(html)
    assert 'target="_blank"' in result
    assert 'rel="noopener noreferrer"' in result


# --- sanitize_html: emoji <img> → :shortcode: preservation ---


def test_sanitize_preserves_emoji_shortcode():
    html = '<p>Hello <img src="https://example.com/emoji/cat.png" alt=":cat:"> world</p>'
    result = sanitize_html(html)
    assert ":cat:" in result
    assert "<img" not in result
    assert "Hello" in result
    assert "world" in result


def test_sanitize_preserves_multiple_emoji():
    html = '<p><img alt=":cat:" src="a.png"> and <img alt=":dog:" src="b.png"></p>'
    result = sanitize_html(html)
    assert ":cat:" in result
    assert ":dog:" in result
    assert "<img" not in result


def test_sanitize_preserves_self_closing_emoji_img():
    html = '<p><img alt=":neko:" src="e.png" /></p>'
    result = sanitize_html(html)
    assert ":neko:" in result


def test_sanitize_does_not_preserve_non_emoji_img():
    """Regular <img> tags without emoji-like alt text are stripped normally."""
    html = '<p>Hello <img src="photo.jpg" alt="A photo"> world</p>'
    result = sanitize_html(html)
    assert "<img" not in result
    assert "A photo" not in result


def test_sanitize_mixed_emoji_and_text():
    html = (
        '<p>Look <img alt=":blobcat:" src="blob.png" class="emoji"> '
        'at this <a href="https://example.com" class="u-url mention">@<span>user</span></a></p>'
    )
    result = sanitize_html(html)
    assert ":blobcat:" in result
    assert "<img" not in result
    assert "user" in result
    assert 'href="https://example.com"' in result


def test_emoji_img_regex_various_formats():
    """EMOJI_IMG_RE matches common emoji img formats from Mastodon/Misskey."""
    # Mastodon format
    assert EMOJI_IMG_RE.search('<img src="url" alt=":blobcat:" class="custom-emoji">')
    # Misskey format
    assert EMOJI_IMG_RE.search('<img alt=":neko:" src="url"/>')
    # Self-closing
    assert EMOJI_IMG_RE.search('<img alt=":cat:" src="url" />')
    # Non-emoji alt should not match
    assert EMOJI_IMG_RE.search('<img alt="photo" src="url">') is None
    assert EMOJI_IMG_RE.search('<img alt=":invalid emoji:" src="url">') is None
