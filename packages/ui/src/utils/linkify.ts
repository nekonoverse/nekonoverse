/**
 * 指定要素内のすべての外部リンクを新しいタブで開くようにする。
 * 内部リンク（メンション、ハッシュタグ、同一オリジンの相対パス）はスキップする。
 */
export function externalLinksNewTab(el: HTMLElement): void {
  const links = el.querySelectorAll<HTMLAnchorElement>("a[href]");
  const currentOrigin = window.location.origin;

  for (const link of links) {
    // メンションやハッシュタグなどの内部リンクはスキップ
    if (link.classList.contains("mention") || link.classList.contains("u-url")) continue;
    if (link.classList.contains("mfm-hashtag")) continue;

    const href = link.getAttribute("href") || "";

    // 相対パスはアプリ内リンクなのでスキップ
    if (href.startsWith("/") || href.startsWith("#")) continue;

    // 同一オリジンのリンクはスキップ
    try {
      const url = new URL(href, currentOrigin);
      if (url.origin === currentOrigin) continue;
    } catch {
      continue;
    }

    link.target = "_blank";
    link.rel = "noopener noreferrer";
  }
}
