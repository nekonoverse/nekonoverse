import { emojiToUrl } from "./twemoji";

const EMOJI_RE =
  /(?:\p{Emoji_Presentation}|\p{Emoji}\uFE0F)(?:\u200D(?:\p{Emoji_Presentation}|\p{Emoji}\uFE0F))*/gu;

/**
 * 要素内のネイティブ Unicode 絵文字を Twemoji <img> タグに置換する。
 * innerHTML 設定後に呼び出すこと。
 */
export function twemojify(el: HTMLElement): void {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  const replacements: { node: Text; frag: DocumentFragment }[] = [];

  let node: Text | null;
  while ((node = walker.nextNode() as Text | null)) {
    const text = node.textContent ?? "";
    if (!EMOJI_RE.test(text)) continue;
    EMOJI_RE.lastIndex = 0;

    const frag = document.createDocumentFragment();
    let lastIdx = 0;
    let match: RegExpExecArray | null;

    while ((match = EMOJI_RE.exec(text))) {
      if (match.index > lastIdx) {
        frag.appendChild(document.createTextNode(text.slice(lastIdx, match.index)));
      }
      const emoji = match[0];
      const img = document.createElement("img");
      img.className = "twemoji";
      img.src = emojiToUrl(emoji);
      img.alt = emoji;
      img.draggable = false;
      frag.appendChild(img);
      lastIdx = match.index + emoji.length;
    }

    if (lastIdx < text.length) {
      frag.appendChild(document.createTextNode(text.slice(lastIdx)));
    }
    replacements.push({ node, frag });
  }

  for (const { node, frag } of replacements) {
    node.parentNode?.replaceChild(frag, node);
  }
}
