import type { CustomEmoji } from "../types/emoji";

const SHORTCODE_RE = /:([a-zA-Z0-9_]+):/g;

/**
 * Replace :shortcode: text in an element with custom emoji <img> tags.
 * Uses the emoji map from the API response to resolve URLs.
 * Call this after setting innerHTML, before twemojify.
 */
export function emojify(el: HTMLElement, emojis: CustomEmoji[]): void {
  if (!emojis || emojis.length === 0) return;

  const emojiMap = new Map<string, CustomEmoji>();
  for (const emoji of emojis) {
    emojiMap.set(emoji.shortcode, emoji);
  }

  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  const replacements: { node: Text; frag: DocumentFragment }[] = [];

  let node: Text | null;
  while ((node = walker.nextNode() as Text | null)) {
    const text = node.textContent ?? "";
    if (!SHORTCODE_RE.test(text)) continue;
    SHORTCODE_RE.lastIndex = 0;

    const frag = document.createDocumentFragment();
    let lastIdx = 0;
    let match: RegExpExecArray | null;
    let hasReplacement = false;

    while ((match = SHORTCODE_RE.exec(text))) {
      const shortcode = match[1];
      const emoji = emojiMap.get(shortcode);
      if (!emoji) continue;

      hasReplacement = true;
      if (match.index > lastIdx) {
        frag.appendChild(document.createTextNode(text.slice(lastIdx, match.index)));
      }
      const img = document.createElement("img");
      img.className = "custom-emoji";
      img.src = emoji.url;
      img.alt = `:${shortcode}:`;
      img.title = `:${shortcode}:`;
      img.draggable = false;
      frag.appendChild(img);
      lastIdx = match.index + match[0].length;
    }

    if (hasReplacement) {
      if (lastIdx < text.length) {
        frag.appendChild(document.createTextNode(text.slice(lastIdx)));
      }
      replacements.push({ node, frag });
    }
  }

  for (const { node, frag } of replacements) {
    node.parentNode?.replaceChild(frag, node);
  }
}
