import re

import bleach

ALLOWED_TAGS = ["a", "br", "p", "span", "em", "strong", "code", "pre", "blockquote"]
ALLOWED_ATTRIBUTES = {"a": ["href", "rel", "class"], "span": ["class"]}

URL_PATTERN = re.compile(r"(https?://[^\s<]+)")
MENTION_PATTERN = re.compile(r"@([a-zA-Z0-9_]+)(?:@([a-zA-Z0-9.-]+))?")


def text_to_html(text: str) -> str:
    """Convert plain text to simple HTML with auto-linking and line breaks."""
    escaped = bleach.clean(text)

    # Auto-link URLs
    escaped = URL_PATTERN.sub(
        r'<a href="\1" rel="nofollow noopener noreferrer" target="_blank">\1</a>',
        escaped,
    )

    # Line breaks
    escaped = escaped.replace("\n", "<br>")

    return f"<p>{escaped}</p>"


def sanitize_html(html: str) -> str:
    """Sanitize HTML from remote sources."""
    return bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, strip=True)
