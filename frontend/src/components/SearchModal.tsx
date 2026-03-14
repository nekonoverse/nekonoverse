import { createSignal, createEffect, onMount, onCleanup, Show, For } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { searchAccounts, type Account } from "@nekonoverse/ui/api/accounts";
import { useI18n } from "../i18n";
import { defaultAvatar } from "../stores/instance";

interface Props {
  onClose: () => void;
}

export default function SearchModal(props: Props) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [query, setQuery] = createSignal("");
  const [results, setResults] = createSignal<Account[]>([]);
  const [searched, setSearched] = createSignal(false);
  const [loading, setLoading] = createSignal(false);
  const [resolving, setResolving] = createSignal(false);

  let inputRef: HTMLInputElement | undefined;
  let debounceTimer: ReturnType<typeof setTimeout> | undefined;

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Escape") props.onClose();
  };

  onMount(() => {
    document.addEventListener("keydown", handleKeyDown);
    document.body.style.overflow = "hidden";
    // Autofocus with a small delay for the modal to render
    setTimeout(() => inputRef?.focus(), 50);
  });

  onCleanup(() => {
    document.removeEventListener("keydown", handleKeyDown);
    document.body.style.overflow = "";
    clearTimeout(debounceTimer);
  });

  const performSearch = async (q: string, resolve: boolean) => {
    const cleaned = q.trim().replace(/^@/, "");
    if (!cleaned) {
      setResults([]);
      setSearched(false);
      setLoading(false);
      setResolving(false);
      return;
    }

    setLoading(true);
    try {
      const data = await searchAccounts(cleaned, resolve);
      // If lookup-style query (user@domain) resolves to exactly 1 result, navigate directly
      if (resolve && cleaned.includes("@") && data.length === 1) {
        navigate(`/@${data[0].acct}`);
        props.onClose();
        return;
      }
      setResults(data);
      setSearched(true);
    } catch {
      // Ignore errors silently
    }
    setLoading(false);
    setResolving(false);
  };

  // Debounced local search on input
  createEffect(() => {
    const q = query();
    clearTimeout(debounceTimer);

    if (!q.trim()) {
      setResults([]);
      setSearched(false);
      setLoading(false);
      setResolving(false);
      return;
    }

    setLoading(true);
    debounceTimer = setTimeout(() => {
      performSearch(q, false);
    }, 300);
  });

  // Submit triggers a resolve search (for remote users)
  const handleSubmit = (e: Event) => {
    e.preventDefault();
    clearTimeout(debounceTimer);
    const q = query().trim();
    if (!q) return;
    setResolving(q.includes("@"));
    setLoading(true);
    performSearch(q, true);
  };

  const handleResultClick = (acct: string) => {
    navigate(`/@${acct}`);
    props.onClose();
  };

  const handleBackdropClick = (e: MouseEvent) => {
    if ((e.target as HTMLElement).classList.contains("search-modal-overlay")) {
      props.onClose();
    }
  };

  return (
    <div class="search-modal-overlay" onClick={handleBackdropClick}>
      <div class="search-modal">
        <form onSubmit={handleSubmit} class="search-modal-header">
          <svg
            class="search-modal-icon"
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            value={query()}
            onInput={(e) => setQuery(e.currentTarget.value)}
            placeholder={t("search.placeholder")}
            class="search-modal-input"
            autocomplete="off"
          />
          <span class="search-modal-hint">{t("search.closeHint")}</span>
          <button
            type="button"
            class="search-modal-close"
            onClick={props.onClose}
            aria-label={t("common.close")}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" stroke-width="2"
              stroke-linecap="round" stroke-linejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </form>

        <div class="search-modal-body">
          <Show when={resolving()}>
            <p class="search-modal-status">{t("search.resolving")}</p>
          </Show>
          <Show when={loading() && !resolving()}>
            <p class="search-modal-status">{t("common.loading")}</p>
          </Show>
          <Show when={!loading() && searched()}>
            <Show
              when={results().length > 0}
              fallback={<p class="search-modal-status">{t("search.noResults")}</p>}
            >
              <div class="search-modal-results">
                <For each={results()}>
                  {(acc) => (
                    <button
                      class="search-modal-result-item"
                      onClick={() => handleResultClick(acc.acct)}
                    >
                      <img
                        class="search-modal-result-avatar"
                        src={acc.avatar || defaultAvatar()}
                        alt=""
                      />
                      <div class="search-modal-result-info">
                        <strong>{acc.display_name || acc.username}</strong>
                        <span class="search-modal-result-handle">@{acc.acct}</span>
                      </div>
                    </button>
                  )}
                </For>
              </div>
            </Show>
          </Show>
        </div>
      </div>
    </div>
  );
}
