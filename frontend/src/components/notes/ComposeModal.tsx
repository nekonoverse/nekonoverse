import { Show, createSignal, createEffect, onCleanup } from "solid-js";
import type { Note } from "@nekonoverse/ui/api/statuses";
import { saveDraft, getInitialVisibility } from "@nekonoverse/ui/stores/composer";
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
  const [confirmOpen, setConfirmOpen] = createSignal(false);
  const [resetKey, setResetKey] = createSignal(0);
  // Track current content for draft save on close
  let currentContent = "";
  let currentVisibility = getInitialVisibility();

  // Reset composer when modal opens
  createEffect(() => {
    if (props.open) {
      setResetKey((k) => k + 1);
      currentContent = "";
      currentVisibility = getInitialVisibility();
      // Auto-focus textarea after render
      requestAnimationFrame(() => {
        const textarea = document.querySelector<HTMLTextAreaElement>(
          ".compose-modal-content textarea"
        );
        textarea?.focus();
      });
    }
  });

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Escape" && props.open) {
      e.preventDefault();
      e.stopPropagation();
      tryClose();
    }
  };

  if (typeof document !== "undefined") {
    document.addEventListener("keydown", handleKeyDown, true);
    onCleanup(() => document.removeEventListener("keydown", handleKeyDown, true));
  }

  const tryClose = () => {
    if (currentContent.trim()) {
      setConfirmOpen(true);
    } else {
      props.onClose();
    }
  };

  const handleOverlayClick = (e: MouseEvent) => {
    if (e.target === overlayRef) tryClose();
  };

  const handlePost = (note: Note) => {
    currentContent = "";
    props.onPost?.(note);
    props.onClose();
  };

  const handleDiscard = () => {
    setConfirmOpen(false);
    currentContent = "";
    props.onClose();
  };

  const handleSaveDraft = () => {
    if (currentContent.trim()) {
      saveDraft(currentContent, currentVisibility);
    }
    setConfirmOpen(false);
    currentContent = "";
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
            <button class="modal-close" onClick={tryClose}>
              &times;
            </button>
          </div>
          <div class="compose-modal-body">
            <NoteComposer
              key={resetKey()}
              onPost={handlePost}
              replyTo={props.replyTo}
              quoteNote={props.quoteNote}
              onContentChange={(content, visibility) => {
                currentContent = content;
                currentVisibility = visibility;
              }}
            />
          </div>
        </div>
      </div>
      <Show when={confirmOpen()}>
        <div class="modal-overlay confirm-overlay" onClick={() => setConfirmOpen(false)}>
          <div class="confirm-dialog" onClick={(e) => e.stopPropagation()}>
            <p>{t("composer.unsavedChanges" as any)}</p>
            <div class="confirm-actions">
              <button class="confirm-btn confirm-discard" onClick={handleDiscard}>
                {t("composer.discard" as any)}
              </button>
              <button class="confirm-btn confirm-save" onClick={handleSaveDraft}>
                {t("composer.saveDraft" as any)}
              </button>
            </div>
          </div>
        </div>
      </Show>
    </Show>
  );
}
