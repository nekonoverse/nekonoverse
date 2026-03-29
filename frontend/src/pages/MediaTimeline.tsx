import { createSignal, createResource, Show, For, onMount, onCleanup } from "solid-js";
import { getMediaTimeline, type Note, type MediaAttachment } from "@nekonoverse/ui/api/statuses";
import { useI18n } from "@nekonoverse/ui/i18n";
import { focalPointToObjectPosition } from "@nekonoverse/ui/utils/focalPoint";
import NoteThreadModal from "../components/notes/NoteThreadModal";

export default function MediaTimeline() {
  const { t } = useI18n();
  const [notes, setNotes] = createSignal<Note[]>([]);
  const [query, setQuery] = createSignal("");
  const [searchInput, setSearchInput] = createSignal("");
  const [loadingMore, setLoadingMore] = createSignal(false);
  const [hasMore, setHasMore] = createSignal(true);
  const [threadNoteId, setThreadNoteId] = createSignal<string | null>(null);

  let sentinelRef: HTMLDivElement | undefined;
  let observer: IntersectionObserver | undefined;
  let debounceTimer: ReturnType<typeof setTimeout> | undefined;

  const LIMIT = 30;

  const [initialData] = createResource(
    () => query(),
    async (q) => {
      const data = await getMediaTimeline({ q: q || undefined, limit: LIMIT });
      setNotes(data);
      setHasMore(data.length >= LIMIT);
      return data;
    },
  );

  const handleSearchInput = (value: string) => {
    setSearchInput(value);
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => setQuery(value), 400);
  };

  const loadOlderNotes = async () => {
    if (loadingMore() || !hasMore()) return;
    const current = notes();
    if (current.length === 0) return;
    const lastId = current[current.length - 1].id;
    setLoadingMore(true);
    try {
      const older = await getMediaTimeline({
        q: query() || undefined,
        max_id: lastId,
        limit: LIMIT,
      });
      if (older.length === 0) {
        setHasMore(false);
      } else {
        setNotes((prev) => {
          const ids = new Set(prev.map((n) => n.id));
          return [...prev, ...older.filter((n) => !ids.has(n.id))];
        });
        if (older.length < LIMIT) setHasMore(false);
      }
    } catch {
      /* ignore */
    } finally {
      setLoadingMore(false);
    }
  };

  onMount(() => {
    observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) loadOlderNotes();
      },
      { rootMargin: "200px" },
    );
    if (sentinelRef) observer.observe(sentinelRef);
  });

  onCleanup(() => {
    observer?.disconnect();
    clearTimeout(debounceTimer);
  });

  const getFirstMedia = (note: Note): MediaAttachment | null => {
    const target = note.reblog || note;
    return (
      target.media_attachments?.find(
        (m) => m.type === "image" || m.type === "gifv" || m.type === "video",
      ) || null
    );
  };

  return (
    <div class="page-container">
      <div class="media-timeline">
        <h2>{t("mediaTimeline.title")}</h2>
        <div class="media-timeline-search">
          <input
            type="text"
            placeholder={t("mediaTimeline.searchPlaceholder")}
            value={searchInput()}
            onInput={(e) => handleSearchInput(e.currentTarget.value)}
            class="media-timeline-search-input"
          />
        </div>
        <Show
          when={initialData.state === "ready" || notes().length > 0}
          fallback={<p class="timeline-loading">{t("timeline.loading")}</p>}
        >
          <Show
            when={notes().length > 0}
            fallback={<p class="empty">{t("mediaTimeline.empty")}</p>}
          >
            <div class="media-gallery-grid">
              <For each={notes()}>
                {(note) => {
                  const media = () => getFirstMedia(note);
                  const target = () => note.reblog || note;
                  const vision = () => media()?.meta?.vision;
                  return (
                    <Show when={media()}>
                      <button
                        class="media-gallery-item"
                        onClick={() => setThreadNoteId(note.id)}
                      >
                        <Show
                          when={!target().sensitive}
                          fallback={
                            <div class="media-gallery-sensitive">
                              <img
                                src={media()!.preview_url || media()!.url}
                                alt=""
                                class="media-gallery-img media-gallery-img-blurred"
                                loading="lazy"
                              />
                              <div class="media-gallery-sensitive-label">
                                {t("sensitive.label")}
                              </div>
                            </div>
                          }
                        >
                          <img
                            src={media()!.preview_url || media()!.url}
                            alt={media()!.description || ""}
                            class="media-gallery-img"
                            loading="lazy"
                            style={{
                              "object-position": focalPointToObjectPosition(
                                media()!.meta?.focus,
                              ),
                            }}
                          />
                        </Show>
                        <div class="media-gallery-overlay">
                          <Show when={vision()?.caption}>
                            <p class="media-gallery-caption">
                              {vision()!.caption}
                            </p>
                          </Show>
                          <Show when={vision()?.tags?.length}>
                            <div class="media-gallery-tags">
                              <For each={vision()!.tags!.slice(0, 5)}>
                                {(tag) => (
                                  <span class="media-gallery-tag">{tag}</span>
                                )}
                              </For>
                            </div>
                          </Show>
                        </div>
                      </button>
                    </Show>
                  );
                }}
              </For>
            </div>
          </Show>
          <div
            ref={(el) => {
              sentinelRef = el;
              if (observer && el) observer.observe(el);
            }}
            class="timeline-sentinel"
          />
          <Show when={loadingMore()}>
            <p class="timeline-loading">{t("timeline.loadingMore")}</p>
          </Show>
          <Show when={!hasMore() && notes().length > 0}>
            <p class="timeline-end">{t("timeline.noMore")}</p>
          </Show>
        </Show>
      </div>
      <Show when={threadNoteId()}>
        <NoteThreadModal
          noteId={threadNoteId()!}
          onClose={() => setThreadNoteId(null)}
        />
      </Show>
    </div>
  );
}
