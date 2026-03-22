import { createSignal, createEffect, onMount, onCleanup, Show, For } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { searchAccounts, type Account } from "@nekonoverse/ui/api/accounts";
import { searchV2 } from "@nekonoverse/ui/api/search";
import type { Note } from "@nekonoverse/ui/api/statuses";
import { useI18n } from "@nekonoverse/ui/i18n";
import { defaultAvatar } from "@nekonoverse/ui/stores/instance";
import { sanitizeHtml } from "@nekonoverse/ui/utils/sanitize";

interface Props {
  onClose: () => void;
}

export default function SearchModal(props: Props) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [query, setQuery] = createSignal("");
  const [accountResults, setAccountResults] = createSignal<Account[]>([]);
  const [noteResults, setNoteResults] = createSignal<Note[]>([]);
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
      setAccountResults([]);
      setNoteResults([]);
      setSearched(false);
      setLoading(false);
      setResolving(false);
      return;
    }

    setLoading(true);
    try {
      if (resolve) {
        // resolve 時は v2 search を使い、ユーザーとノートの両方を検索
        const data = await searchV2(cleaned, true);
        // URL照会でノート1件のみ → 直接遷移
        if (cleaned.startsWith("https://") && data.statuses.length === 1) {
          navigate(`/notes/${data.statuses[0].id}`);
          props.onClose();
          return;
        }
        // user@domain照会でユーザー1件のみ → 直接遷移
        if (cleaned.includes("@") && !cleaned.startsWith("https://")
            && data.accounts.length === 1) {
          navigate(`/@${data.accounts[0].acct}`);
          props.onClose();
          return;
        }
        setAccountResults(data.accounts);
        setNoteResults(data.statuses);
      } else {
        // 入力中はローカルユーザー検索のみ（軽量）
        const data = await searchAccounts(cleaned, false);
        setAccountResults(data);
        setNoteResults([]);
      }
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
      setAccountResults([]);
      setNoteResults([]);
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

  // Submit triggers a resolve search (for remote users/notes)
  const handleSubmit = (e: Event) => {
    e.preventDefault();
    clearTimeout(debounceTimer);
    const q = query().trim();
    if (!q) return;
    setResolving(q.includes("@") || q.startsWith("https://"));
    setLoading(true);
    performSearch(q, true);
  };

  const handleAccountClick = (acct: string) => {
    navigate(`/@${acct}`);
    props.onClose();
  };

  const handleNoteClick = (noteId: string) => {
    navigate(`/notes/${noteId}`);
    props.onClose();
  };

  const handleBackdropClick = (e: MouseEvent) => {
    if ((e.target as HTMLElement).classList.contains("search-modal-overlay")) {
      props.onClose();
    }
  };

  const hasResults = () => accountResults().length > 0 || noteResults().length > 0;

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
              when={hasResults()}
              fallback={<p class="search-modal-status">{t("search.noResults")}</p>}
            >
              <div class="search-modal-results">
                <For each={accountResults()}>
                  {(acc) => (
                    <button
                      class="search-modal-result-item"
                      onClick={() => handleAccountClick(acc.acct)}
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
                <For each={noteResults()}>
                  {(note) => (
                    <button
                      class="search-modal-result-item"
                      onClick={() => handleNoteClick(note.id)}
                    >
                      <img
                        class="search-modal-result-avatar"
                        src={note.account.avatar || defaultAvatar()}
                        alt=""
                      />
                      <div class="search-modal-result-info">
                        <strong>{note.account.display_name || note.account.username}</strong>
                        <span
                          class="search-modal-result-preview"
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
      </div>
    </div>
  );
}
