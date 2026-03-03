import { createSignal, onMount, Show, For } from "solid-js";
import { currentUser, authLoading, fetchCurrentUser } from "../stores/auth";
import { fetchInstance, registrationOpen } from "../stores/instance";
import { getPublicTimeline, type Note } from "../api/statuses";
import { useI18n } from "../i18n";
import NoteComposer from "../components/notes/NoteComposer";
import NoteCard from "../components/notes/NoteCard";

export default function Home() {
  const { t } = useI18n();
  const [notes, setNotes] = createSignal<Note[]>([]);
  const [timelineLoading, setTimelineLoading] = createSignal(true);

  const loadTimeline = async () => {
    setTimelineLoading(true);
    try {
      const data = await getPublicTimeline({ local: true });
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

  const handleNewNote = (note: Note) => {
    setNotes((prev) => [note, ...prev]);
  };

  return (
    <div class="page-container">
      <h1>{t("app.title")}</h1>
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
          <NoteComposer onPost={handleNewNote} />
        </Show>
      </Show>

      <div class="timeline">
        <h2>{t("timeline.public")}</h2>
        <Show when={!timelineLoading()} fallback={<p>{t("timeline.loading")}</p>}>
          <Show when={notes().length > 0} fallback={<p class="empty">{t("timeline.empty")}</p>}>
            <For each={notes()}>{(note) => <NoteCard note={note} />}</For>
          </Show>
        </Show>
      </div>
    </div>
  );
}
