/**
 * Nyaize text transformation for is_cat users.
 * Misskey-compatible: replaces な→にゃ, na→nya, etc.
 * Operates on text nodes only to avoid breaking HTML tags/attributes.
 */

const NYAIZE_JA: [RegExp, string][] = [
  [/な/g, "にゃ"],
  [/ナ/g, "ニャ"],
  [/ﾅ/g, "ﾆｬ"],
];

const NYAIZE_EN: [RegExp, string][] = [
  [/(?<=n)a/gi, (m: string) => (m === "A" ? "YA" : "ya")],
  [/(?<=morn)ing/gi, "yan"],
  [/(?<=every)one/gi, "nyan"],
] as unknown as [RegExp, string][];

/**
 * Apply nyaize transformation to a plain text string.
 */
export function nyaizeText(text: string): string {
  let result = text;
  for (const [pattern, replacement] of NYAIZE_JA) {
    result = result.replace(pattern, replacement);
  }
  for (const [pattern, replacement] of NYAIZE_EN) {
    result = result.replace(pattern, replacement as string);
  }
  return result;
}

/**
 * Apply nyaize to all text nodes in a DOM element.
 * Skips code, pre, a (href), and other non-text elements.
 */
export function nyaizeElement(el: HTMLElement): void {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      if (!parent) return NodeFilter.FILTER_ACCEPT;
      const tag = parent.tagName;
      if (tag === "CODE" || tag === "PRE" || tag === "A" || tag === "SCRIPT") {
        return NodeFilter.FILTER_REJECT;
      }
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const nodes: Text[] = [];
  let current: Node | null;
  while ((current = walker.nextNode())) {
    nodes.push(current as Text);
  }
  for (const node of nodes) {
    const transformed = nyaizeText(node.textContent || "");
    if (transformed !== node.textContent) {
      node.textContent = transformed;
    }
  }
}
