import { createSignal, createEffect, onCleanup, Show, For } from "solid-js";
import { useSearchParams, useNavigate } from "@solidjs/router";
import { searchV2, searchSuggest } from "@nekonoverse/ui/api/search";
import { getNote, type Note } from "@nekonoverse/ui/api/statuses";
import { onReaction } from "@nekonoverse/ui/stores/streaming";
import { currentUser } from "@nekonoverse/ui/stores/auth";
import { useI18n } from "@nekonoverse/ui/i18n";
import NoteCard from "../components/notes/NoteCard";
import NoteThreadModal from "../components/notes/NoteThreadModal";

export default function Search() {
  const { t } = useI18n();
  const navigate = useNavigate();

  if (!currentUser()) {
    navigate("/login", { replace: true });
    return null;
  }
  const [searchParams, setSearchParams] = useSearchParams();
  const [query, setQuery] = createSignal(searchParams.q ?? "");
  const [noteResults, setNoteResults] = createSignal<Note[]>([]);
  const [searched, setSearched] = createSignal(false);
  const [loading, setLoading] = createSignal(false);
  const [suggestions, setSuggestions] = createSignal<{ token: string; df: number }[]>([]);
  const [threadNoteId, setThreadNoteId] = createSignal<string | null>(null);

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
    setSearchParams({ q: cleaned });
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

  // Auto-search if q param is present on load
  if (searchParams.q) {
    performSearch(searchParams.q);
  }

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

  const refreshNote = async (noteId: string) => {
    try {
      const updated = await getNote(noteId);
      setNoteResults((prev) => prev.map((n) => {
        if (n.id === noteId) return updated;
        if (n.reblog?.id === noteId) return { ...n, reblog: updated };
        return n;
      }));
    } catch {}
  };

  const unsubReaction = onReaction(async (data) => {
    const { id } = data as { id: string };
    if (!id) return;
    if (noteResults().some((n) => n.id === id || n.reblog?.id === id)) {
      await refreshNote(id);
    }
  });
  onCleanup(() => unsubReaction());

  return (
    <div class="page-container">
      <h1>{t("search.fullSearchTitle")}</h1>
      <form onSubmit={handleSubmit} class="search-form">
        <input
          type="text"
          value={query()}
          onInput={(e) => setQuery(e.currentTarget.value)}
          placeholder={t("search.fullSearchPlaceholder")}
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
          <For each={noteResults()}>
            {(note) => (
              <NoteCard
                note={note}
                onReactionUpdate={() => refreshNote(note.id)}
                onDelete={(id) => setNoteResults((prev) => prev.filter((n) => n.id !== id))}
                onThreadOpen={(id) => setThreadNoteId(id)}
              />
            )}
          </For>
        </Show>
      </Show>

      <Show when={threadNoteId()}>
        <NoteThreadModal
          noteId={threadNoteId()!}
          onClose={() => setThreadNoteId(null)}
        />
      </Show>
    </div>
  );
}
