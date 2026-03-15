import {
  createSignal,
  createEffect,
  on,
  onMount,
  onCleanup,
  Show,
  For,
  untrack,
} from "solid-js";
import { useSearchParams, useNavigate } from "@solidjs/router";
import { currentUser, authLoading } from "@nekonoverse/ui/stores/auth";
import EntrancePage from "../components/entrance/EntrancePage";
import {
  getPublicTimeline,
  getHomeTimeline,
  getNote,
  type Note,
} from "@nekonoverse/ui/api/statuses";
import { onUpdate, onReaction } from "@nekonoverse/ui/stores/streaming";
import { useI18n } from "@nekonoverse/ui/i18n";
import NoteComposer from "../components/notes/NoteComposer";
import NoteCard from "../components/notes/NoteCard";

export default function Home() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [notes, setNotes] = createSignal<Note[]>([]);
  const [initialLoading, setInitialLoading] = createSignal(true);
  const [quoteTarget, setQuoteTarget] = createSignal<Note | null>(null);
  const [newNoteIds, setNewNoteIds] = createSignal<Set<string>>(new Set());

  // Infinite scroll state
  const [loadingMore, setLoadingMore] = createSignal(false);
  const [hasMore, setHasMore] = createSignal(true);

  // New post buffering state
  const [bufferedNotes, setBufferedNotes] = createSignal<Note[]>([]);
  const [isAtTop, setIsAtTop] = createSignal(true);

  // Scroll-to-top button state
  const [showScrollTop, setShowScrollTop] = createSignal(false);

  let sentinelRef: HTMLDivElement | undefined;
  let observer: IntersectionObserver | undefined;

  // Callback ref: observe sentinel as soon as it appears in the DOM
  const setSentinelRef = (el: HTMLDivElement) => {
    sentinelRef = el;
    if (observer && el) {
      observer.observe(el);
    }
  };

  const isHomeTL = () => {
    const tl = searchParams.tl ?? localStorage.getItem("nekonoverse:tl");
    return tl === "home" && !!currentUser();
  };

  const loadTimeline = async () => {
    try {
      const data = untrack(isHomeTL)
        ? await getHomeTimeline()
        : await getPublicTimeline();
      setNotes(data);
      setHasMore(data.length >= 20);
      setBufferedNotes([]);
    } catch {
      // ignore
    } finally {
      setInitialLoading(false);
    }
  };

  // Load older posts (infinite scroll)
  const loadOlderNotes = async () => {
    if (loadingMore() || !hasMore()) return;
    const current = notes();
    if (current.length === 0) return;
    const lastId = current[current.length - 1].id;
    setLoadingMore(true);
    try {
      const data = untrack(isHomeTL)
        ? await getHomeTimeline({ max_id: lastId })
        : await getPublicTimeline({ max_id: lastId });
      if (data.length === 0) {
        setHasMore(false);
      } else {
        setNotes((prev) => {
          const existingIds = new Set(prev.map((n) => n.id));
          const unique = data.filter((n) => !existingIds.has(n.id));
          return [...prev, ...unique];
        });
        if (data.length < 20) {
          setHasMore(false);
        }
      }
    } catch {
      // ignore
    } finally {
      setLoadingMore(false);
      // Re-observe sentinel: IntersectionObserver only fires on state *changes*,
      // so if the sentinel is still in view after appending notes we must
      // reset observation to trigger the next page load.
      if (observer && sentinelRef && hasMore()) {
        observer.unobserve(sentinelRef);
        observer.observe(sentinelRef);
      }
    }
  };

  // Scroll position tracking for new post buffering and scroll-to-top button
  const handleScroll = () => {
    const y = window.scrollY;
    setIsAtTop(y < 100);
    setShowScrollTop(y > 500);
  };

  const scrollToTop = () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  // Flush buffered notes into the timeline
  const flushBuffer = () => {
    const buffered = bufferedNotes();
    if (buffered.length === 0) return;
    setNotes((prev) => {
      const existingIds = new Set(prev.map((n) => n.id));
      const unique = buffered.filter((n) => !existingIds.has(n.id));
      return [...unique, ...prev];
    });
    // Apply slide-in animation to flushed notes
    for (const n of buffered) {
      setNewNoteIds((s) => new Set(s).add(n.id));
      setTimeout(
        () =>
          setNewNoteIds((s) => {
            const next = new Set(s);
            next.delete(n.id);
            return next;
          }),
        600,
      );
    }
    setBufferedNotes([]);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  // When user scrolls back to top, auto-flush buffer
  createEffect(() => {
    if (isAtTop() && bufferedNotes().length > 0) {
      flushBuffer();
    }
  });

  // Initial load: wait for auth to settle (App.tsx Layout handles fetchCurrentUser)
  let loaded = false;
  createEffect(() => {
    if (!authLoading() && !loaded) {
      loaded = true;
      loadTimeline();
    }
  });

  // Subscribe to real-time timeline updates from global stream
  const unsub = onUpdate(async (data) => {
    const { id } = data as { id: string };
    if (!id) return;
    try {
      const note = await getNote(id);
      // On public timeline, only show public notes (match REST API filtering)
      if (!isHomeTL() && note.visibility !== "public") {
        return;
      }
      // If this note already exists (directly, as reblog, or as quote),
      // update it in-place (handles focal point updates, edits, etc.)
      const inTimeline = notes().some(
        (n) => n.id === id || n.reblog?.id === id || n.quote?.id === id,
      );
      if (inTimeline) {
        setNotes((prev) =>
          prev.map((n) => {
            if (n.id === id) return note;
            if (n.reblog?.id === id) return { ...n, reblog: note };
            if (n.quote?.id === id) return { ...n, quote: note };
            return n;
          }),
        );
        return;
      }
      if (
        bufferedNotes().some(
          (n) => n.id === id || n.reblog?.id === id || n.quote?.id === id,
        )
      )
        return;

      if (isAtTop()) {
        // User is at top: insert directly with animation
        setNotes((prev) => {
          if (prev.some((n) => n.id === id)) return prev;
          return [note, ...prev];
        });
        setNewNoteIds((s) => new Set(s).add(id));
        setTimeout(
          () =>
            setNewNoteIds((s) => {
              const next = new Set(s);
              next.delete(id);
              return next;
            }),
          600,
        );
      } else {
        // User is scrolling: buffer the note
        setBufferedNotes((prev) => {
          if (prev.some((n) => n.id === id)) return prev;
          return [note, ...prev];
        });
      }
    } catch {
      /* ignore */
    }
  });

  // リアクション更新のデバウンス (同一Noteへの連続更新を集約)
  const pendingReactionRefresh = new Map<
    string,
    ReturnType<typeof setTimeout>
  >();
  const unsubReaction = onReaction(async (data) => {
    const { id } = data as { id: string };
    if (!id) return;
    if (notes().some((n) => n.id === id || n.reblog?.id === id)) {
      const existing = pendingReactionRefresh.get(id);
      if (existing) clearTimeout(existing);
      pendingReactionRefresh.set(
        id,
        setTimeout(async () => {
          pendingReactionRefresh.delete(id);
          await refreshNote(id);
        }, 500),
      );
    }
  });

  onMount(() => {
    window.addEventListener("scroll", handleScroll, { passive: true });

    // IntersectionObserver for infinite scroll
    observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          loadOlderNotes();
        }
      },
      { rootMargin: "200px" },
    );
    // If sentinel already rendered (e.g. fast load), observe it now
    if (sentinelRef) {
      observer.observe(sentinelRef);
    }
  });

  onCleanup(() => {
    unsub();
    unsubReaction();
    pendingReactionRefresh.forEach((timer) => clearTimeout(timer));
    pendingReactionRefresh.clear();
    window.removeEventListener("scroll", handleScroll);
    if (observer) {
      observer.disconnect();
    }
  });

  // Reload only when tl search param changes (explicit dependency)
  createEffect(
    on(
      () => searchParams.tl,
      () => {
        if (loaded) {
          setHasMore(true);
          setBufferedNotes([]);
          loadTimeline();
        }
      },
      { defer: true },
    ),
  );

  const handleNewNote = (note: Note) => {
    if (!isHomeTL() && note.visibility !== "public") {
      // 公開TL表示中にunlisted等を投稿した場合はホームTLに遷移
      navigate("/?tl=home");
      return;
    }
    setNotes((prev) => [note, ...prev]);
  };

  const refreshNote = async (noteId: string) => {
    try {
      const updated = await getNote(noteId);
      setNotes((prev) =>
        prev.map((n) => {
          if (n.id === noteId) return updated;
          if (n.reblog?.id === noteId) return { ...n, reblog: updated };
          return n;
        }),
      );
    } catch {
      // ignore
    }
  };

  return (
    <div class="page-container">
      <Show when={!authLoading()} fallback={<p>{t("common.loading")}</p>}>
        <Show when={currentUser()} fallback={<EntrancePage />}>
          <NoteComposer
            onPost={handleNewNote}
            quoteNote={quoteTarget()}
            onClearQuote={() => setQuoteTarget(null)}
          />

          <div class="timeline">
            <h2>{isHomeTL() ? t("timeline.home") : t("timeline.public")}</h2>

            {/* New posts banner */}
            <Show when={bufferedNotes().length > 0}>
              <button class="new-posts-banner" onClick={flushBuffer}>
                {t("timeline.newPosts").replace(
                  "{count}",
                  String(bufferedNotes().length),
                )}
              </button>
            </Show>

            <Show
              when={!initialLoading()}
              fallback={<p>{t("timeline.loading")}</p>}
            >
              <Show
                when={notes().length > 0}
                fallback={<p class="empty">{t("timeline.empty")}</p>}
              >
                <For each={notes()}>
                  {(note) => (
                    <div
                      class={newNoteIds().has(note.id) ? "note-slide-in" : ""}
                    >
                      <NoteCard
                        note={note}
                        onReactionUpdate={() => refreshNote(note.id)}
                        onQuote={(n) => {
                          setQuoteTarget(n);
                          window.scrollTo({ top: 0, behavior: "smooth" });
                        }}
                        onDelete={(id) =>
                          setNotes((prev) => prev.filter((n) => n.id !== id))
                        }
                      />
                    </div>
                  )}
                </For>
              </Show>

              {/* Sentinel element for infinite scroll */}
              <div ref={setSentinelRef} class="timeline-sentinel" />

              {/* Loading indicator */}
              <Show when={loadingMore()}>
                <p class="timeline-loading">{t("timeline.loadingMore")}</p>
              </Show>

              {/* End of timeline */}
              <Show when={!hasMore() && notes().length > 0}>
                <p class="timeline-end">{t("timeline.noMore")}</p>
              </Show>
            </Show>
          </div>

          {/* Scroll-to-top floating button */}
          <Show when={showScrollTop()}>
            <button
              class="scroll-to-top"
              onClick={scrollToTop}
              aria-label={t("timeline.scrollToTop")}
              title={t("timeline.scrollToTop")}
            >
              <svg
                width="20"
                height="20"
                viewBox="0 0 20 20"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
                aria-hidden="true"
              >
                <path d="M10 3L3 10h4v7h6v-7h4L10 3z" fill="currentColor" />
              </svg>
            </button>
          </Show>
        </Show>
      </Show>
    </div>
  );
}
