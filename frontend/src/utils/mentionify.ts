/**
 * Post-process mention links in rendered HTML to show full handle for remote users.
 * Converts "@username" to "@username@domain" when the mention href points to a remote server.
 * Call this after setting innerHTML.
 */
export function mentionify(el: HTMLElement): void {
  const currentHost = window.location.hostname;
  const mentions = el.querySelectorAll<HTMLAnchorElement>("a.u-url.mention");

  for (const link of mentions) {
    try {
      const url = new URL(link.href);
      if (url.hostname === currentHost) continue;

      // 内部の<span>要素を探す
      const span = link.querySelector("span");
      if (!span) continue;

      // すでにドメインが付与済みならスキップ
      if (span.textContent?.includes("@")) continue;

      span.textContent = `${span.textContent}@${url.hostname}`;
    } catch {
      // URL解析失敗時はスキップ
    }
  }
}
