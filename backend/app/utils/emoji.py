import re
import unicodedata

# Match a single emoji character (including compound emoji with ZWJ)
# This covers most Unicode emoji: Emoji_Presentation, skin tone modifiers, ZWJ sequences
_EMOJI_PATTERN = re.compile(
    r"^(?:"
    r"[\U0001F600-\U0001F64F]"  # Emoticons
    r"|[\U0001F300-\U0001F5FF]"  # Misc Symbols and Pictographs
    r"|[\U0001F680-\U0001F6FF]"  # Transport and Map
    r"|[\U0001F1E0-\U0001F1FF]"  # Flags (Regional Indicator)
    r"|[\U00002702-\U000027B0]"  # Dingbats
    r"|[\U0001F900-\U0001F9FF]"  # Supplemental Symbols and Pictographs
    r"|[\U0001FA00-\U0001FA6F]"  # Chess, Extended-A
    r"|[\U0001FA70-\U0001FAFF]"  # Extended-A cont.
    r"|[\U00002600-\U000026FF]"  # Misc Symbols
    r"|[\U0000FE00-\U0000FE0F]"  # Variation Selectors
    r"|[\U0000200D]"  # ZWJ
    r"|[\U0000200B-\U0000200F]"  # Zero-width chars
    r"|[\U0000FE0E-\U0000FE0F]"  # Variation selectors
    r"|[\U0001F000-\U0001F02F]"  # Mahjong
    r"|[\U00002702-\U000027B0]"  # Dingbats
    r"|[\U000023E9-\U000023F3]"  # Misc technical
    r"|[\U000023F8-\U000023FA]"  # Misc technical
    r"|[\U0000231A-\U0000231B]"  # Watch/Hourglass
    r"|[\U000025AA-\U000025AB]"  # Small squares
    r"|[\U000025B6]"  # Play
    r"|[\U000025C0]"  # Reverse
    r"|[\U000025FB-\U000025FE]"  # Squares
    r"|[\U00002934-\U00002935]"  # Arrows
    r"|[\U00002B05-\U00002B07]"  # Arrows
    r"|[\U00002B1B-\U00002B1C]"  # Squares
    r"|[\U00002B50]"  # Star
    r"|[\U00002B55]"  # Circle
    r"|[\U00003030]"  # Wavy dash
    r"|[\U0000303D]"  # Part alt mark
    r"|[\U00003297]"  # Circled Ideograph Congratulation
    r"|[\U00003299]"  # Circled Ideograph Secret
    r"|[\U0000200D]"  # ZWJ
    r"|[\U0000FE0F]"  # VS16
    r"|[\U000020E3]"  # Combining Enclosing Keycap
    r"|[\U0001F3FB-\U0001F3FF]"  # Skin tone modifiers
    r")+"
    r"$"
)


def is_single_emoji(text: str) -> bool:
    """Check if a string is a single emoji (possibly a compound one with ZWJ)."""
    if not text or len(text) > 20:
        return False

    text = text.strip()
    if not text:
        return False

    # Use the pattern for common emoji
    if _EMOJI_PATTERN.match(text):
        return True

    # Fallback: check if all characters have emoji category
    for char in text:
        cat = unicodedata.category(char)
        if cat not in ("So", "Sk", "Mn", "Mc", "Cf", "Cn"):
            return False

    return len(text) > 0
