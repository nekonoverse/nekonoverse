const TWEMOJI_BASE =
  "https://cdn.jsdelivr.net/gh/jdecked/twemoji@latest/assets/svg";

/** Convert an emoji string to its Twemoji SVG URL. */
export function emojiToUrl(emoji: string): string {
  const codepoints = [...emoji]
    .map((c) => c.codePointAt(0)!.toString(16))
    .filter((cp) => cp !== "fe0f")
    .join("-");
  return `${TWEMOJI_BASE}/${codepoints}.svg`;
}
