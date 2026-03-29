/**
 * is_cat ユーザー用のにゃ化テキスト変換。
 * Misskey 互換: な→にゃ, na→nya などを置換。
 * HTML タグ/属性を壊さないようテキストノードのみに適用する。
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
 * プレーンテキスト文字列ににゃ化変換を適用する。
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
 * DOM 要素内のすべてのテキストノードににゃ化を適用する。
 * code, pre, a (href) などの非テキスト要素はスキップする。
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
