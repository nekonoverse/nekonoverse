import { createSignal, createEffect, Show, For } from "solid-js";
import { useParams } from "@solidjs/router";
import { getTagTimeline, getNote, type Note } from "../api/statuses";
import { useI18n } from "../i18n";
import NoteCard from "../components/notes/NoteCard";

export default function TagTimeline() {
  const { t } = useI18n();
  const params = useParams<{ tag: string }>();
  const [notes, setNotes] = createSignal<Note[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [loadingMore, setLoadingMore] = createSignal(false);

  const loadTimeline = async () => {
    setLoading(true);
    try {
      const data = await getTagTimeline(params.tag);
      setNotes(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  createEffect(() => {
    // Re-run whenever the tag param changes
    const _tag = params.tag;
    loadTimeline();
  });

  const loadMore = async () => {
    const current = notes();
    if (current.length === 0 || loadingMore()) return;
    setLoadingMore(true);
    try {
      const lastId = current[current.length - 1].id;
      const older = await getTagTimeline(params.tag, { max_id: lastId });
      if (older.length > 0) {
        setNotes([...current, ...older]);
      }
    } catch {
      // ignore
    } finally {
      setLoadingMore(false);
    }
  };

  const refreshNote = async (noteId: string) => {
    try {
      const updated = await getNote(noteId);
      setNotes((prev) => prev.map((n) => (n.id === noteId ? updated : n)));
    } catch {
      // ignore
    }
  };

  return (
    <div class="page-container">
      <div class="timeline">
        <h2 class="tag-timeline-header">#{params.tag}</h2>
        <Show when={!loading()} fallback={<p>{t("timeline.loading")}</p>}>
          <Show
            when={notes().length > 0}
            fallback={<p class="empty">{t("hashtag.empty")}</p>}
          >
            <For each={notes()}>
              {(note) => (
                <NoteCard
                  note={note}
                  onReactionUpdate={() => refreshNote(note.id)}
                  onDelete={(id) =>
                    setNotes((prev) => prev.filter((n) => n.id !== id))
                  }
                />
              )}
            </For>
            <div class="load-more-container">
              <button
                class="btn btn-secondary"
                onClick={loadMore}
                disabled={loadingMore()}
              >
                {loadingMore() ? t("common.loading") : t("hashtag.loadMore")}
              </button>
            </div>
          </Show>
        </Show>
      </div>
    </div>
  );
}
