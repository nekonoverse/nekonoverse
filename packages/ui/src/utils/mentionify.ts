/**
 * Post-process mention links in rendered HTML to show full handle for remote users.
 * Rewrites remote mention hrefs to local profile paths (/@user@domain) and
 * intercepts clicks to navigate within the app via SolidJS Router.
 * Also converts "@username" display text to "@username@domain" with styled domain.
 * Call this after setting innerHTML.
 *
 * Handles various AP implementation formats:
 * - Mastodon:    <a class="u-url mention">@<span>user</span></a>
 * - Pleroma/GoToSocial: <a class="mention">@user</a> (no inner span)
 */
export function mentionify(
  el: HTMLElement,
  navigate?: (path: string) => void,
): void {
  const currentHost = window.location.hostname;
  // Broad selector: some AP implementations omit the u-url class
  const mentions = el.querySelectorAll<HTMLAnchorElement>("a.mention");

  for (const link of mentions) {
    // Mastodon hashtag links have class="mention hashtag" — skip them
    if (link.classList.contains("hashtag")) continue;

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
      if (span) {
        // Mastodon形式: <a>@<span>username</span></a>
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
      } else {
        // Pleroma/GoToSocial形式: <a class="mention">@username</a> (spanなし)
        const rawText = link.textContent || "";
        const username = rawText.replace(/^@/, "");
        if (username && !username.includes("@")) {
          // ドメインがない場合、hrefから補完
          link.textContent = "";
          const inner = document.createElement("span");
          inner.textContent = `@${username}`;
          const domainSpan = document.createElement("span");
          domainSpan.className = "mention-domain";
          domainSpan.textContent = `@${url.hostname}`;
          inner.appendChild(domainSpan);
          link.appendChild(inner);
        } else if (username && username.includes("@")) {
          // ドメインが既にテキストに含まれている場合、分割してスタイル適用
          const atIdx = username.indexOf("@");
          const user = username.slice(0, atIdx);
          const domain = username.slice(atIdx);
          link.textContent = "";
          const inner = document.createElement("span");
          inner.textContent = `@${user}`;
          const domainSpan = document.createElement("span");
          domainSpan.className = "mention-domain";
          domainSpan.textContent = domain;
          inner.appendChild(domainSpan);
          link.appendChild(inner);
        }
      }
    } catch {
      // URL解析失敗時はスキップ
    }
  }
}
