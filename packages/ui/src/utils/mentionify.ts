/**
 * レンダリング済み HTML のメンションリンクを後処理し、リモートユーザーのフルハンドルを表示する。
 * リモートメンションの href をローカルプロフィールパス (/@user@domain) に書き換え、
 * クリックを傍受して SolidJS Router でアプリ内ナビゲーションを行う。
 * また "@username" 表示テキストを "@username@domain" に変換し、ドメイン部分にスタイルを適用する。
 * innerHTML を設定した後に呼び出すこと。
 *
 * 各種 AP 実装のフォーマットに対応:
 * - Mastodon:    <a class="u-url mention">@<span>user</span></a>
 * - Pleroma/GoToSocial: <a class="mention">@user</a> (内側の span なし)
 */
export function mentionify(
  el: HTMLElement,
  navigate?: (path: string) => void,
): void {
  const currentHost = window.location.hostname;
  // 広めのセレクタ: 一部の AP 実装は u-url クラスを省略する
  const mentions = el.querySelectorAll<HTMLAnchorElement>("a.mention");

  for (const link of mentions) {
    // Mastodon のハッシュタグリンクは class="mention hashtag" — スキップ
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
