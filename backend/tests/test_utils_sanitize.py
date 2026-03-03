from app.utils.sanitize import sanitize_html, text_to_html


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
