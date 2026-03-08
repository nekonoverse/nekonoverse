/**
 * Post-process mention links in rendered HTML to show full handle for remote users.
 * Rewrites remote mention hrefs to local profile paths (/@user@domain) so that
 * clicking them navigates within the app and triggers WebFinger lookup.
 * Also converts "@username" display text to "@username@domain".
 * Call this after setting innerHTML.
 */
export function mentionify(el: HTMLElement): void {
  const currentHost = window.location.hostname;
  const mentions = el.querySelectorAll<HTMLAnchorElement>("a.u-url.mention");

  for (const link of mentions) {
    try {
      const url = new URL(link.href);
      if (url.hostname === currentHost) continue;

      // リモートメンションのhrefをローカルプロフィールパスに書き換え
      const pathUser = url.pathname.replace(/^\/@?/, "");
      if (pathUser) {
        link.href = `/@${pathUser}@${url.hostname}`;
      }

      const span = link.querySelector("span");
      if (!span) continue;
      if (span.textContent?.includes("@")) continue;
      span.textContent = `${span.textContent}@${url.hostname}`;
    } catch {
      // URL解析失敗時はスキップ
    }
  }
}
