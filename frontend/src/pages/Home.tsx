import { createSignal, createEffect, on, onCleanup, Show, For, untrack } from "solid-js";
import { useSearchParams } from "@solidjs/router";
import { currentUser, authLoading } from "../stores/auth";
import { registrationMode } from "../stores/instance";
import { getPublicTimeline, getHomeTimeline, getNote, type Note } from "../api/statuses";
import { onUpdate, onReaction } from "../stores/streaming";
import { useI18n } from "../i18n";
import NoteComposer from "../components/notes/NoteComposer";
import NoteCard from "../components/notes/NoteCard";

export default function Home() {
  const { t } = useI18n();
  const [searchParams] = useSearchParams();
  const [notes, setNotes] = createSignal<Note[]>([]);
  const [initialLoading, setInitialLoading] = createSignal(true);
  const [quoteTarget, setQuoteTarget] = createSignal<Note | null>(null);
  const [newNoteIds, setNewNoteIds] = createSignal<Set<string>>(new Set());

  const isHomeTL = () => searchParams.tl === "home" && !!currentUser();

  const loadTimeline = async () => {
    try {
      const data = untrack(isHomeTL)
        ? await getHomeTimeline()
        : await getPublicTimeline();
      setNotes(data);
    } catch {
      // ignore
    } finally {
      setInitialLoading(false);
    }
  };

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
      setNotes((prev) => {
        if (prev.some((n) => n.id === id)) return prev;
        return [note, ...prev];
      });
      setNewNoteIds((s) => new Set(s).add(id));
      setTimeout(() => setNewNoteIds((s) => { const next = new Set(s); next.delete(id); return next; }), 600);
    } catch { /* ignore */ }
  });

  const unsubReaction = onReaction(async (data) => {
    const { id } = data as { id: string };
    if (!id) return;
    if (notes().some((n) => n.id === id || n.reblog?.id === id)) {
      await refreshNote(id);
    }
  });

  onCleanup(() => { unsub(); unsubReaction(); });

  // Reload only when tl search param changes (explicit dependency)
  createEffect(on(
    () => searchParams.tl,
    () => { if (loaded) loadTimeline(); },
    { defer: true }
  ));

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
                <Show when={registrationMode() !== "closed"}>
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
        <Show when={!initialLoading()} fallback={<p>{t("timeline.loading")}</p>}>
          <Show when={notes().length > 0} fallback={<p class="empty">{t("timeline.empty")}</p>}>
            <For each={notes()}>{(note) => <div class={newNoteIds().has(note.id) ? "note-slide-in" : ""}><NoteCard note={note} onReactionUpdate={() => refreshNote(note.id)} onQuote={(n) => { setQuoteTarget(n); window.scrollTo({ top: 0, behavior: "smooth" }); }} onDelete={(id) => setNotes((prev) => prev.filter((n) => n.id !== id))} /></div>}</For>
          </Show>
        </Show>
      </div>
    </div>
  );
}
