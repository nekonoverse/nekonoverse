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


# --- text_to_html: emoji_map → <img> replacement ---


def test_text_to_html_emoji_map_basic():
    """Emoji shortcodes are replaced with <img> tags when emoji_map is provided."""
    emoji_map = {"blobcat": "https://example.com/emoji/blobcat.png"}
    result = text_to_html("Hello :blobcat: world", emoji_map=emoji_map)
    assert '<img src="https://example.com/emoji/blobcat.png"' in result
    assert 'alt=":blobcat:"' in result
    assert 'class="custom-emoji"' in result
    assert 'style="height: 1.5em; vertical-align: middle"' in result


def test_text_to_html_emoji_map_multiple():
    """Multiple emoji shortcodes are all replaced."""
    emoji_map = {
        "cat": "https://example.com/emoji/cat.png",
        "dog": "https://example.com/emoji/dog.png",
    }
    result = text_to_html(":cat: and :dog:", emoji_map=emoji_map)
    assert 'alt=":cat:"' in result
    assert 'alt=":dog:"' in result
    assert result.count("<img") == 2


def test_text_to_html_emoji_map_unknown_shortcode():
    """Unknown shortcodes remain as plain text."""
    emoji_map = {"cat": "https://example.com/emoji/cat.png"}
    result = text_to_html(":cat: and :unknown:", emoji_map=emoji_map)
    assert 'alt=":cat:"' in result
    assert ":unknown:" in result
    assert result.count("<img") == 1


def test_text_to_html_emoji_map_none():
    """When emoji_map is None, shortcodes remain as text."""
    result = text_to_html("Hello :blobcat:")
    assert "<img" not in result
    assert ":blobcat:" in result


def test_text_to_html_emoji_map_empty():
    """When emoji_map is empty dict, shortcodes remain as text."""
    result = text_to_html("Hello :blobcat:", emoji_map={})
    assert "<img" not in result
    assert ":blobcat:" in result


def test_text_to_html_emoji_not_replaced_in_url():
    """Emoji shortcodes inside auto-linked URLs should not be replaced."""
    emoji_map = {"cat": "https://example.com/emoji/cat.png"}
    result = text_to_html("See https://example.com/:cat:/page", emoji_map=emoji_map)
    # The :cat: inside the URL should not be turned into an <img> tag
    assert 'href="https://example.com/:cat:/page"' in result


def test_text_to_html_emoji_with_mentions():
    """Emoji replacement works alongside mentions."""
    emoji_map = {"blobcat": "https://example.com/emoji/blobcat.png"}
    result = text_to_html("@alice :blobcat:", emoji_map=emoji_map)
    assert 'class="u-url mention"' in result
    assert 'alt=":blobcat:"' in result


def test_text_to_html_emoji_with_line_breaks():
    """Emoji replacement works with line breaks."""
    emoji_map = {"cat": "https://example.com/emoji/cat.png"}
    result = text_to_html(":cat:\nnew line", emoji_map=emoji_map)
    assert 'alt=":cat:"' in result
    assert "<br>" in result
