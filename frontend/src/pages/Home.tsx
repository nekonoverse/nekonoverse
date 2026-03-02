import { createSignal, onMount, Show, For } from "solid-js";
import { currentUser, authLoading, fetchCurrentUser } from "../stores/auth";
import { getPublicTimeline, type Note } from "../api/statuses";
import NoteComposer from "../components/notes/NoteComposer";
import NoteCard from "../components/notes/NoteCard";

export default function Home() {
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
    await fetchCurrentUser();
    await loadTimeline();
  });

  const handleNewNote = (note: Note) => {
    setNotes((prev) => [note, ...prev]);
  };

  return (
    <div class="page-container">
      <h1>Nekonoverse</h1>
      <Show when={!authLoading()} fallback={<p>Loading...</p>}>
        <Show
          when={currentUser()}
          fallback={
            <div>
              <p>A cat-friendly ActivityPub server</p>
              <div class="home-actions">
                <a href="/login" class="btn">Login</a>
                <a href="/register" class="btn btn-secondary">Register</a>
              </div>
            </div>
          }
        >
          <NoteComposer onPost={handleNewNote} />
        </Show>
      </Show>

      <div class="timeline">
        <h2>Public Timeline</h2>
        <Show when={!timelineLoading()} fallback={<p>Loading timeline...</p>}>
          <Show when={notes().length > 0} fallback={<p class="empty">No posts yet.</p>}>
            <For each={notes()}>{(note) => <NoteCard note={note} />}</For>
          </Show>
        </Show>
      </div>
    </div>
  );
}
