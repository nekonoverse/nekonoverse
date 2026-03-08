import { createSignal, onMount, onCleanup, Show, For } from "solid-js";
import { getBookmarks, getNote, type Note } from "../api/statuses";
import { currentUser, authLoading, fetchCurrentUser } from "../stores/auth";
import { onReaction } from "../stores/streaming";
import NoteCard from "../components/notes/NoteCard";
import { useI18n } from "../i18n";

export default function Bookmarks() {
  const { t } = useI18n();
  const [notes, setNotes] = createSignal<Note[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [hasMore, setHasMore] = createSignal(false);

  const LIMIT = 20;

  const load = async (maxId?: string) => {
    try {
      const data = await getBookmarks({ limit: LIMIT + 1, max_id: maxId });
      setHasMore(data.length > LIMIT);
      const items = data.slice(0, LIMIT);
      if (maxId) {
        setNotes((prev) => [...prev, ...items]);
      } else {
        setNotes(items);
      }
    } catch {}
    setLoading(false);
  };

  onMount(async () => {
    await fetchCurrentUser();
    await load();
  });

  const loadMore = () => {
    const last = notes().at(-1);
    if (last) load(last.id);
  };

  const refreshNote = async (noteId: string) => {
    try {
      const updated = await getNote(noteId);
      setNotes((prev) => prev.map((n) => (n.id === noteId ? updated : n)));
    } catch {}
  };

  const unsubReaction = onReaction(async (data) => {
    const { id } = data as { id: string };
    if (!id) return;
    if (notes().some((n) => n.id === id || n.reblog?.id === id)) {
      await refreshNote(id);
    }
  });
  onCleanup(() => unsubReaction());

  return (
    <div class="page-container">
      <h1>{t("bookmark.title")}</h1>
      <Show when={!authLoading()} fallback={<p>{t("common.loading")}</p>}>
        <Show when={currentUser()} fallback={<p>{t("bookmark.loginRequired")}</p>}>
          <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
            <Show when={notes().length > 0} fallback={<p class="empty">{t("bookmark.empty")}</p>}>
              <For each={notes()}>
                {(note) => (
                  <NoteCard
                    note={note}
                    onReactionUpdate={() => refreshNote(note.id)}
                    onDelete={(id) => setNotes((prev) => prev.filter((n) => n.id !== id))}
                  />
                )}
              </For>
              <Show when={hasMore()}>
                <button class="btn load-more-btn" onClick={loadMore}>
                  {t("notifications.loadMore")}
                </button>
              </Show>
            </Show>
          </Show>
        </Show>
      </Show>
    </div>
  );
}
