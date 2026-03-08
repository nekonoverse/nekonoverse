import { createSignal, createEffect, onMount, onCleanup, Show, For } from "solid-js";
import { useSearchParams } from "@solidjs/router";
import { currentUser, authLoading, fetchCurrentUser } from "../stores/auth";
import { fetchInstance, registrationOpen } from "../stores/instance";
import { getPublicTimeline, getHomeTimeline, getNote, type Note } from "../api/statuses";
import { onUpdate } from "../stores/streaming";
import { useI18n } from "../i18n";
import NoteComposer from "../components/notes/NoteComposer";
import NoteCard from "../components/notes/NoteCard";

export default function Home() {
  const { t } = useI18n();
  const [searchParams] = useSearchParams();
  const [notes, setNotes] = createSignal<Note[]>([]);
  const [timelineLoading, setTimelineLoading] = createSignal(true);
  const [quoteTarget, setQuoteTarget] = createSignal<Note | null>(null);

  const isHomeTL = () => searchParams.tl === "home" && !!currentUser();

  const loadTimeline = async () => {
    setTimelineLoading(true);
    try {
      const data = isHomeTL()
        ? await getHomeTimeline()
        : await getPublicTimeline({ local: true });
      setNotes(data);
    } catch {
      // ignore
    } finally {
      setTimelineLoading(false);
    }
  };

  onMount(async () => {
    await Promise.all([fetchCurrentUser(), fetchInstance()]);
    await loadTimeline();
  });

  // Subscribe to real-time timeline updates from global stream
  const unsub = onUpdate(async (data) => {
    const { id } = data as { id: string };
    if (!id) return;
    try {
      const note = await getNote(id);
      setNotes((prev) => {
        if (prev.some((n) => n.id === id)) return prev;
        return [note, ...prev];
      });
    } catch { /* ignore */ }
  });

  onCleanup(unsub);

  // Reload when switching between public/home
  createEffect(() => {
    const _ = searchParams.tl;
    if (!authLoading()) {
      loadTimeline();
    }
  });

  const handleNewNote = (note: Note) => {
    setNotes((prev) => [note, ...prev]);
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
      <Show when={!authLoading()} fallback={<p>{t("common.loading")}</p>}>
        <Show
          when={currentUser()}
          fallback={
            <div>
              <p>{t("app.tagline")}</p>
              <div class="home-actions">
                <a href="/login" class="btn">{t("common.login")}</a>
                <Show when={registrationOpen()}>
                  <a href="/register" class="btn btn-secondary">{t("common.register")}</a>
                </Show>
              </div>
            </div>
          }
        >
          <NoteComposer onPost={handleNewNote} quoteNote={quoteTarget()} onClearQuote={() => setQuoteTarget(null)} />
        </Show>
      </Show>

      <div class="timeline">
        <h2>{isHomeTL() ? t("timeline.home") : t("timeline.public")}</h2>
        <Show when={!timelineLoading()} fallback={<p>{t("timeline.loading")}</p>}>
          <Show when={notes().length > 0} fallback={<p class="empty">{t("timeline.empty")}</p>}>
            <For each={notes()}>{(note) => <NoteCard note={note} onReactionUpdate={() => refreshNote(note.id)} onQuote={(n) => { setQuoteTarget(n); window.scrollTo({ top: 0, behavior: "smooth" }); }} onDelete={(id) => setNotes((prev) => prev.filter((n) => n.id !== id))} />}</For>
          </Show>
        </Show>
      </div>
    </div>
  );
}
