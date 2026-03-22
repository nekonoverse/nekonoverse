"""ActivityPub protocol helpers."""

# Source mediaTypes that are safe to render as MFM (Misskey Flavored Markdown).
# text/x.misskeymarkdown: MFM itself
# text/plain: plain text is valid MFM; Nekonoverse also historically sent this
MFM_MEDIA_TYPES = frozenset({"text/x.misskeymarkdown", "text/plain"})


def extract_mfm_source(note_data: dict) -> str | None:
    """Extract MFM-compatible source text from an AP Note object.

    Returns source.content only when mediaType is MFM-compatible,
    falling back to _misskey_content (always MFM).
    Returns None if no MFM source is available.
    """
    source_data = note_data.get("source")
    if isinstance(source_data, dict):
        media_type = source_data.get("mediaType")
        if media_type is None or media_type in MFM_MEDIA_TYPES:
            content = source_data.get("content")
            if isinstance(content, str):
                return content

    # Misskey fallback: _misskey_content is always MFM
    misskey_content = note_data.get("_misskey_content")
    if isinstance(misskey_content, str):
        return misskey_content

    return None


def resolve_source_media_type(source: str, preferences: dict | None = None) -> str:
    """Determine the outbound source.mediaType based on user preferences.

    Preference values:
      "mfm"   -> always text/x.misskeymarkdown
      "plain" -> always text/plain
      "auto"  -> text/x.misskeymarkdown if MFM-specific syntax found, else text/plain
    """
    pref = (preferences or {}).get("source_media_type", "auto")
    if pref == "mfm":
        return "text/x.misskeymarkdown"
    if pref == "plain":
        return "text/plain"
    # auto: detect MFM-specific function syntax
    if "$[" in source:
        return "text/x.misskeymarkdown"
    return "text/plain"
