import { createSignal } from "solid-js";
import { createNote, type Note } from "../../api/statuses";
import { useI18n } from "../../i18n";
import {
  getInitialVisibility,
  rememberVisibility,
  defaultVisibility,
  setLastVisibility,
  type Visibility,
} from "../../stores/composer";
import VisibilitySelector from "./VisibilitySelector";

interface Props {
  onPost?: (note: Note) => void;
}

export default function NoteComposer(props: Props) {
  const { t } = useI18n();
  const [content, setContent] = createSignal("");
  const [visibility, setVisibility] = createSignal<Visibility>(getInitialVisibility());
  const [loading, setLoading] = createSignal(false);
  const [error, setError] = createSignal("");

  const handleSubmit = async (e: Event) => {
    e.preventDefault();
    if (!content().trim()) return;
    setLoading(true);
    setError("");
    try {
      const note = await createNote(content(), visibility());
      setContent("");

      if (rememberVisibility()) {
        setLastVisibility(visibility());
      } else {
        setVisibility(defaultVisibility());
      }

      props.onPost?.(note);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("composer.failed"));
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
        placeholder={t("composer.placeholder")}
        rows={3}
        maxLength={5000}
      />
      <div class="composer-footer">
        <span class="char-count">{content().length} / 5000</span>
        <div class="composer-actions">
          <VisibilitySelector value={visibility()} onChange={setVisibility} />
          <button type="submit" disabled={loading() || !content().trim()}>
            {loading() ? t("composer.posting") : t("composer.post")}
          </button>
        </div>
      </div>
    </form>
  );
}
