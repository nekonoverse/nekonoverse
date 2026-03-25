import { createSignal, createEffect, Show, For } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { searchV2, searchSuggest } from "@nekonoverse/ui/api/search";
import type { Note } from "@nekonoverse/ui/api/statuses";
import { useI18n } from "@nekonoverse/ui/i18n";
import { defaultAvatar } from "@nekonoverse/ui/stores/instance";
import { sanitizeHtml } from "@nekonoverse/ui/utils/sanitize";

export default function Search() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [query, setQuery] = createSignal("");
  const [noteResults, setNoteResults] = createSignal<Note[]>([]);
  const [searched, setSearched] = createSignal(false);
  const [loading, setLoading] = createSignal(false);
  const [suggestions, setSuggestions] = createSignal<{ token: string; df: number }[]>([]);

  let inputRef: HTMLInputElement | undefined;
  let debounceTimer: ReturnType<typeof setTimeout> | undefined;

  // Debounced suggest on input
  createEffect(() => {
    const q = query();
    clearTimeout(debounceTimer);

    if (!q.trim()) {
      setSuggestions([]);
      return;
    }

    debounceTimer = setTimeout(() => {
      searchSuggest(q).then((r) => setSuggestions(r.suggestions)).catch(() => setSuggestions([]));
    }, 200);
  });

  const performSearch = async (q: string) => {
    const cleaned = q.trim();
    if (!cleaned) return;
    setLoading(true);
    setSuggestions([]);
    try {
      const data = await searchV2(cleaned, false);
      setNoteResults(data.statuses);
      setSearched(true);
    } catch {
      // Ignore errors silently
    }
    setLoading(false);
  };

  const handleSubmit = (e: Event) => {
    e.preventDefault();
    clearTimeout(debounceTimer);
    performSearch(query());
  };

  const handleSuggestionClick = (token: string) => {
    const display = token.replace(/^▁/, "");
    setQuery(display);
    setSuggestions([]);
    performSearch(display);
  };

  const handleNoteClick = (noteId: string) => {
    navigate(`/notes/${noteId}`);
  };

  return (
    <div class="page-container">
      <h1>{t("search.fullSearchTitle")}</h1>
      <form onSubmit={handleSubmit} class="search-form">
        <input
          ref={inputRef}
          type="text"
          value={query()}
          onInput={(e) => setQuery(e.currentTarget.value)}
          placeholder={t("search.placeholder")}
          class="search-input"
          autocomplete="off"
          autofocus
        />
        <button type="submit" class="btn" disabled={loading()}>
          {t("search.fullSearchTitle")}
        </button>
      </form>
      <Show when={suggestions().length > 0}>
        <div class="search-modal-suggestions">
          <For each={suggestions()}>
            {(s) => (
              <button
                class="search-modal-suggestion-item"
                onClick={() => handleSuggestionClick(s.token)}
              >
                <span>{s.token.replace(/^▁/, "")}</span>
                <span class="search-modal-suggestion-df">{s.df}</span>
              </button>
            )}
          </For>
        </div>
      </Show>
      <Show when={loading()}>
        <p>{t("common.loading")}</p>
      </Show>
      <Show when={searched() && !loading()}>
        <Show
          when={noteResults().length > 0}
          fallback={<p class="empty">{t("search.noResults")}</p>}
        >
          <div class="search-results">
            <For each={noteResults()}>
              {(note) => (
                <button
                  class="search-result-item"
                  onClick={() => handleNoteClick(note.id)}
                >
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
                </button>
              )}
            </For>
          </div>
        </Show>
      </Show>
    </div>
  );
}
