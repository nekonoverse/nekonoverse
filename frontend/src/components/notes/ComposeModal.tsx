import { Show, onMount, onCleanup } from "solid-js";
import type { Note } from "@nekonoverse/ui/api/statuses";
import NoteComposer from "./NoteComposer";
import { useI18n } from "@nekonoverse/ui/i18n";

interface Props {
  open: boolean;
  onClose: () => void;
  onPost?: (note: Note) => void;
  replyTo?: Note | null;
  quoteNote?: Note | null;
}

export default function ComposeModal(props: Props) {
  const { t } = useI18n();
  let overlayRef: HTMLDivElement | undefined;

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Escape") props.onClose();
  };

  onMount(() => {
    document.addEventListener("keydown", handleKeyDown);
    onCleanup(() => document.removeEventListener("keydown", handleKeyDown));
  });

  const handleOverlayClick = (e: MouseEvent) => {
    if (e.target === overlayRef) props.onClose();
  };

  const handlePost = (note: Note) => {
    props.onPost?.(note);
    props.onClose();
  };

  return (
    <Show when={props.open}>
      <div class="modal-overlay" ref={overlayRef} onClick={handleOverlayClick}>
        <div class="modal-content compose-modal-content">
          <div class="modal-header">
            <h3>
              {props.replyTo
                ? t("composer.reply")
                : props.quoteNote
                  ? t("composer.quote")
                  : t("composer.new")}
            </h3>
            <button class="modal-close" onClick={() => props.onClose()}>
              &times;
            </button>
          </div>
          <div class="compose-modal-body">
            <NoteComposer
              onPost={handlePost}
              replyTo={props.replyTo}
              quoteNote={props.quoteNote}
            />
          </div>
        </div>
      </div>
    </Show>
  );
}
