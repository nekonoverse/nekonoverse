import { createSignal, Show, For } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { type Account } from "@nekonoverse/ui/api/accounts";
import { searchV2 } from "@nekonoverse/ui/api/search";
import type { Note } from "@nekonoverse/ui/api/statuses";
import { useI18n } from "@nekonoverse/ui/i18n";
import { defaultAvatar } from "@nekonoverse/ui/stores/instance";
import { sanitizeHtml } from "@nekonoverse/ui/utils/sanitize";

export default function Search() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [query, setQuery] = createSignal("");
  const [accountResults, setAccountResults] = createSignal<Account[]>([]);
  const [noteResults, setNoteResults] = createSignal<Note[]>([]);
  const [searched, setSearched] = createSignal(false);
  const [loading, setLoading] = createSignal(false);

  const handleSearch = async (e?: Event) => {
    e?.preventDefault();
    const q = query().trim().replace(/^@/, "");
    if (!q) return;
    setLoading(true);
    try {
      const data = await searchV2(q, true);
      // URL照会でノート1件 → 直接遷移
      if (q.startsWith("https://") && data.statuses.length === 1) {
        navigate(`/notes/${data.statuses[0].id}`);
        return;
      }
      // user@domain照会でユーザー1件 → 直接遷移
      if (q.includes("@") && !q.startsWith("https://") && data.accounts.length === 1) {
        navigate(`/@${data.accounts[0].acct}`);
        return;
      }
      setAccountResults(data.accounts);
      setNoteResults(data.statuses);
      setSearched(true);
    } catch {}
    setLoading(false);
  };

  const hasResults = () => accountResults().length > 0 || noteResults().length > 0;

  return (
    <div class="page-container">
      <h1>{t("search.title")}</h1>
      <form onSubmit={handleSearch} class="search-form">
        <input
          type="text"
          value={query()}
          onInput={(e) => setQuery(e.currentTarget.value)}
          placeholder={t("search.placeholder")}
          class="search-input"
        />
        <button type="submit" class="btn" disabled={loading()}>
          {t("search.search")}
        </button>
      </form>
      <Show when={loading()}>
        <p>{t("common.loading")}</p>
      </Show>
      <Show when={searched() && !loading()}>
        <Show
          when={hasResults()}
          fallback={<p class="empty">{t("search.noResults")}</p>}
        >
          <div class="search-results">
            <For each={accountResults()}>
              {(acc) => (
                <a href={`/@${acc.acct}`} class="search-result-item">
                  <img
                    class="search-result-avatar"
                    src={acc.avatar || defaultAvatar()}
                    alt=""
                  />
                  <div class="search-result-info">
                    <strong>{acc.display_name || acc.username}</strong>
                    <span class="search-result-handle">@{acc.acct}</span>
                  </div>
                </a>
              )}
            </For>
            <For each={noteResults()}>
              {(note) => (
                <a href={`/notes/${note.id}`} class="search-result-item">
                  <img
                    class="search-result-avatar"
                    src={note.account.avatar || defaultAvatar()}
                    alt=""
                  />
                  <div class="search-result-info">
                    <strong>{note.account.display_name || note.account.username}</strong>
                    <span
                      class="search-result-preview"
                      ref={(el) => {
                        el.innerHTML = sanitizeHtml(note.content);
                      }}
                    />
                  </div>
                </a>
              )}
            </For>
          </div>
        </Show>
      </Show>
    </div>
  );
}
