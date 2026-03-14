import re

import bleach

ALLOWED_TAGS = ["a", "br", "p", "span", "em", "strong", "code", "pre", "blockquote"]
ALLOWED_ATTRIBUTES = {"a": ["href", "rel", "class", "target"], "span": ["class"]}

URL_PATTERN = re.compile(r"(https?://[^\s<]+)")
MENTION_PATTERN = re.compile(r"@([a-zA-Z0-9_]+)(?:@([a-zA-Z0-9.-]+))?")
EMOJI_IMG_RE = re.compile(
    r'<img\b[^>]*\balt="(:[a-zA-Z0-9_]+:)"[^>]*/?>',
    re.IGNORECASE,
)


def _replace_mention(match: re.Match) -> str:
    """Replace a mention match with an HTML link."""
    username = match.group(1)
    domain = match.group(2)

    if domain:
        href = f"https://{domain}/@{username}"
    else:
        from app.config import settings

        href = f"{settings.server_url}/@{username}"

    if domain:
        display_html = f'{username}<span class="mention-domain">@{domain}</span>'
    else:
        display_html = username

    return (
        f'<span class="h-card">'
        f'<a href="{href}" class="u-url mention">@<span>{display_html}</span></a>'
        f"</span>"
    )


def text_to_html(text: str) -> str:
    """Convert plain text to simple HTML with auto-linking, mentions, and line breaks."""
    escaped = bleach.clean(text)

    # Auto-link URLs first (before mention parsing)
    escaped = URL_PATTERN.sub(
        r'<a href="\1" rel="nofollow noopener noreferrer" target="_blank">\1</a>',
        escaped,
    )

    # Parse mentions (skip inside existing <a> tags)
    parts = re.split(r"(<a[^>]*>.*?</a>)", escaped)
    result = []
    for part in parts:
        if part.startswith("<a"):
            result.append(part)
        else:
            result.append(MENTION_PATTERN.sub(_replace_mention, part))
    escaped = "".join(result)

    # Line breaks
    escaped = escaped.replace("\n", "<br>")

    return f"<p>{escaped}</p>"


ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


def sanitize_html(html: str) -> str:
    """Sanitize HTML from remote sources."""
    html = EMOJI_IMG_RE.sub(r"\1", html)
    return bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )
