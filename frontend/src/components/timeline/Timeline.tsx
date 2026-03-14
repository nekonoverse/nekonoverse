import { createSignal, onMount, For, Show } from "solid-js";
import { getPublicTimeline, type Note } from "@nekonoverse/ui/api/statuses";
import NoteCard from "../notes/NoteCard";

export default function Timeline() {
  const [notes, setNotes] = createSignal<Note[]>([]);
  const [loading, setLoading] = createSignal(true);

  const load = async () => {
    setLoading(true);
    try {
      const data = await getPublicTimeline({ local: true });
      setNotes(data);
    } catch {
      // ignore for now
    } finally {
      setLoading(false);
    }
  };

  onMount(load);

  const prependNote = (note: Note) => {
    setNotes((prev) => [note, ...prev]);
  };

  return { notes, loading, prependNote, reload: load };
}
