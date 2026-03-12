/**
 * Post-process mention links in rendered HTML to show full handle for remote users.
 * Rewrites remote mention hrefs to local profile paths (/@user@domain) and
 * intercepts clicks to navigate within the app via SolidJS Router.
 * Also converts "@username" display text to "@username@domain" with styled domain.
 * Call this after setting innerHTML.
 */
export function mentionify(
  el: HTMLElement,
  navigate?: (path: string) => void,
): void {
  const currentHost = window.location.hostname;
  const mentions = el.querySelectorAll<HTMLAnchorElement>("a.u-url.mention");

  for (const link of mentions) {
    try {
      const url = new URL(link.href);
      if (url.hostname === currentHost) continue;

      // リモートメンションのhrefをローカルプロフィールパスに書き換え
      const pathUser = url.pathname.replace(/^\/@?/, "");
      if (pathUser) {
        const localPath = `/@${pathUser}@${url.hostname}`;
        link.setAttribute("href", localPath);

        // クリック時にSolidJS Routerでクライアントサイドナビゲーション
        if (navigate) {
          link.addEventListener("click", (e) => {
            if (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
            e.preventDefault();
            navigate(localPath);
          });
        }
      }

      // ドメインスタイリング: 既存の .mention-domain があればスキップ
      if (link.querySelector(".mention-domain")) continue;

      const span = link.querySelector("span");
      if (!span) continue;

      const text = span.textContent || "";
      if (text.includes("@")) {
        // テキストにドメインが含まれている場合、分割してスタイル適用
        const atIdx = text.indexOf("@");
        const username = text.slice(0, atIdx);
        const domain = text.slice(atIdx);
        span.textContent = username;
        const domainSpan = document.createElement("span");
        domainSpan.className = "mention-domain";
        domainSpan.textContent = domain;
        span.appendChild(domainSpan);
      } else {
        // ドメインがない場合、hrefから補完
        const domainSpan = document.createElement("span");
        domainSpan.className = "mention-domain";
        domainSpan.textContent = `@${url.hostname}`;
        span.appendChild(domainSpan);
      }
    } catch {
      // URL解析失敗時はスキップ
    }
  }
}
