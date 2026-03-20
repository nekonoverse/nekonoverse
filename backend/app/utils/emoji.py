import re
import unicodedata

CUSTOM_EMOJI_PATTERN = re.compile(r"^:([a-zA-Z0-9_]+)(?:@([a-zA-Z0-9.-]+))?:$")

# Match a single emoji character (including compound emoji with ZWJ)
# This covers most Unicode emoji: Emoji_Presentation, skin tone modifiers, ZWJ sequences
_EMOJI_PATTERN = re.compile(
    r"^["
    r"\U0001F600-\U0001F64F"  # Emoticons
    r"\U0001F300-\U0001F5FF"  # Misc Symbols and Pictographs
    r"\U0001F680-\U0001F6FF"  # Transport and Map
    r"\U0001F1E0-\U0001F1FF"  # Flags (Regional Indicator)
    r"\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
    r"\U0001FA00-\U0001FA6F"  # Chess, Extended-A
    r"\U0001FA70-\U0001FAFF"  # Extended-A cont.
    r"\U0001F000-\U0001F02F"  # Mahjong
    r"\U0001F3FB-\U0001F3FF"  # Skin tone modifiers
    r"\U00002600-\U000027B0"  # Misc Symbols + Dingbats
    r"\U0000231A-\U0000231B"  # Watch/Hourglass
    r"\U000023E9-\U000023F3"  # Misc technical
    r"\U000023F8-\U000023FA"  # Misc technical
    r"\U000025AA-\U000025AB"  # Small squares
    r"\U000025B6"             # Play
    r"\U000025C0"             # Reverse
    r"\U000025FB-\U000025FE"  # Squares
    r"\U00002934-\U00002935"  # Arrows
    r"\U00002B05-\U00002B07"  # Arrows
    r"\U00002B1B-\U00002B1C"  # Squares
    r"\U00002B50"             # Star
    r"\U00002B55"             # Circle
    r"\U00003030"             # Wavy dash
    r"\U0000303D"             # Part alt mark
    r"\U00003297"             # Circled Ideograph Congratulation
    r"\U00003299"             # Circled Ideograph Secret
    r"\U0000200B-\U0000200F"  # Zero-width chars (incl. ZWJ)
    r"\U0000FE00-\U0000FE0F"  # Variation Selectors
    r"\U000020E3"             # Combining Enclosing Keycap
    r"]+$"
)


def _is_single_emoji_sequence(text: str) -> bool:
    """Check if text is a single emoji sequence (handles ZWJ, flags, skin tones)."""
    if not text:
        return False

    # Check if it contains ZWJ — if so, it's a compound emoji (e.g. family)
    if "\u200d" in text:
        # All non-ZWJ, non-modifier chars should be emoji
        return True

    # Count base emoji characters (excluding modifiers and variation selectors)
    count = 0
    i = 0
    while i < len(text):
        cp = ord(text[i])
        # Skip variation selectors and other modifiers
        if cp in (0xFE0F, 0xFE0E, 0x20E3) or 0x200B <= cp <= 0x200F:
            i += 1
            continue
        if 0x1F3FB <= cp <= 0x1F3FF:  # Skin tone modifiers
            i += 1
            continue
        # Regional indicators come in pairs for flags
        if 0x1F1E0 <= cp <= 0x1F1FF:
            if i + 1 < len(text) and 0x1F1E0 <= ord(text[i + 1]) <= 0x1F1FF:
                count += 1
                i += 2
                continue
        count += 1
        i += 1
    return count == 1


def is_single_emoji(text: str) -> bool:
    """Check if a string is a single emoji (possibly a compound one with ZWJ)."""
    if not text or len(text) > 20:
        return False

    text = text.strip()
    if not text:
        return False

    # Use the pattern for common emoji
    if _EMOJI_PATTERN.match(text):
        return _is_single_emoji_sequence(text)

    # Fallback: check if all characters have emoji category
    for char in text:
        cat = unicodedata.category(char)
        if cat not in ("So", "Sk", "Mn", "Mc", "Cf", "Cn"):
            return False

    return len(text) > 0 and _is_single_emoji_sequence(text)


def is_custom_emoji_shortcode(text: str) -> bool:
    """Check if text is a custom emoji shortcode like :blobcat: or :emoji@domain:"""
    return bool(CUSTOM_EMOJI_PATTERN.match(text.strip()))
