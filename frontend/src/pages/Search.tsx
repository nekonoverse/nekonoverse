import { createSignal, Show, For } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { searchAccounts, type Account } from "@nekonoverse/ui/api/accounts";
import { useI18n } from "../i18n";
import { defaultAvatar } from "../stores/instance";

export default function Search() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [query, setQuery] = createSignal("");
  const [results, setResults] = createSignal<Account[]>([]);
  const [searched, setSearched] = createSignal(false);
  const [loading, setLoading] = createSignal(false);

  const handleSearch = async (e?: Event) => {
    e?.preventDefault();
    const q = query().trim().replace(/^@/, "");
    if (!q) return;
    setLoading(true);
    try {
      const data = await searchAccounts(q, true);
      // Auto-navigate if lookup-style query (user@domain) resolves to exactly 1 result
      if (q.includes("@") && data.length === 1) {
        navigate(`/@${data[0].acct}`);
        return;
      }
      setResults(data);
      setSearched(true);
    } catch {}
    setLoading(false);
  };

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
          when={results().length > 0}
          fallback={<p class="empty">{t("search.noResults")}</p>}
        >
          <div class="search-results">
            <For each={results()}>
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
          </div>
        </Show>
      </Show>
    </div>
  );
}
