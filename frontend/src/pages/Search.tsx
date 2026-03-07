import { createSignal, Show, For } from "solid-js";
import { searchAccounts, type Account } from "../api/accounts";
import { useI18n } from "../i18n";

export default function Search() {
  const { t } = useI18n();
  const [query, setQuery] = createSignal("");
  const [results, setResults] = createSignal<Account[]>([]);
  const [searched, setSearched] = createSignal(false);
  const [loading, setLoading] = createSignal(false);

  const handleSearch = async (e?: Event) => {
    e?.preventDefault();
    if (!query().trim()) return;
    setLoading(true);
    try {
      const data = await searchAccounts(query(), true);
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
                    src={acc.avatar || "/default-avatar.svg"}
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
