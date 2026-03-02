import { createSignal } from "solid-js";
import { createNote, type Note } from "../../api/statuses";

interface Props {
  onPost?: (note: Note) => void;
}

export default function NoteComposer(props: Props) {
  const [content, setContent] = createSignal("");
  const [loading, setLoading] = createSignal(false);
  const [error, setError] = createSignal("");

  const handleSubmit = async (e: Event) => {
    e.preventDefault();
    if (!content().trim()) return;
    setLoading(true);
    setError("");
    try {
      const note = await createNote(content());
      setContent("");
      props.onPost?.(note);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to post");
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} class="note-composer">
      {error() && <div class="error">{error()}</div>}
      <textarea
        value={content()}
        onInput={(e) => setContent(e.currentTarget.value)}
        placeholder="What's on your mind?"
        rows={3}
        maxLength={5000}
      />
      <div class="composer-footer">
        <span class="char-count">{content().length} / 5000</span>
        <button type="submit" disabled={loading() || !content().trim()}>
          {loading() ? "Posting..." : "Post"}
        </button>
      </div>
    </form>
  );
}
