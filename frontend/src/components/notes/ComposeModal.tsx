import { Show, For, createSignal, createEffect, onCleanup } from "solid-js";
import type { Note } from "@nekonoverse/ui/api/statuses";
import { saveDraft, drafts, deleteDraft, getInitialVisibility, type Visibility } from "@nekonoverse/ui/stores/composer";
import NoteComposer from "./NoteComposer";
import { useI18n } from "@nekonoverse/ui/i18n";
import type { Dictionary } from "@nekonoverse/ui/i18n/dictionaries/ja";

interface Props {
  open: boolean;
  onClose: () => void;
  onPost?: (note: Note) => void;
  replyTo?: Note | null;
  quoteNote?: Note | null;
}

const VIS_EMOJI: Record<string, string> = {
  public: "\u{1F310}",
  unlisted: "\u{1F513}",
  followers: "\u{1F512}",
  direct: "\u2709\uFE0F",
};

export default function ComposeModal(props: Props) {
  const { t } = useI18n();
  let overlayRef: HTMLDivElement | undefined;
  const [confirmOpen, setConfirmOpen] = createSignal(false);
  const [resetKey, setResetKey] = createSignal(0);
  const [draftContent, setDraftContent] = createSignal<string | undefined>(undefined);
  const [draftVisibility, setDraftVisibility] = createSignal<Visibility | undefined>(undefined);
  // Track current content for draft save on close
  let currentContent = "";
  let currentVisibility = getInitialVisibility();

  // Whether to show draft picker (new compose with no reply/quote context)
  const showDrafts = () =>
    props.open && !currentContent.trim() && !props.replyTo && !props.quoteNote && drafts().length > 0 && !draftContent();

  // Reset composer when modal opens
  createEffect(() => {
    if (props.open) {
      setResetKey((k) => k + 1);
      currentContent = "";
      currentVisibility = getInitialVisibility();
      setDraftContent(undefined);
      setDraftVisibility(undefined);
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

  const loadDraft = (draft: { id: string; content: string; visibility: Visibility }) => {
    setDraftContent(draft.content);
    setDraftVisibility(draft.visibility);
    deleteDraft(draft.id);
    setResetKey((k) => k + 1);
    requestAnimationFrame(() => {
      const textarea = document.querySelector<HTMLTextAreaElement>(
        ".compose-modal-content textarea"
      );
      textarea?.focus();
    });
  };

  const formatDraftTime = (ts: number) => {
    const d = new Date(ts);
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
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
          <Show when={showDrafts()}>
            <div class="compose-drafts">
              <div class="compose-drafts-header">
                <span>{t("composer.drafts" as keyof Dictionary)}</span>
              </div>
              <div class="compose-drafts-list">
                <For each={drafts()}>
                  {(draft) => (
                    <div class="compose-draft-item" onClick={() => loadDraft(draft)}>
                      <div class="compose-draft-content">
                        <span class="compose-draft-vis">{VIS_EMOJI[draft.visibility] || ""}</span>
                        <span class="compose-draft-text">
                          {draft.content.length > 80 ? draft.content.slice(0, 80) + "..." : draft.content}
                        </span>
                      </div>
                      <div class="compose-draft-meta">
                        <span class="compose-draft-time">{formatDraftTime(draft.createdAt)}</span>
                        <button
                          class="compose-draft-delete"
                          onClick={(e) => { e.stopPropagation(); deleteDraft(draft.id); }}
                          title={t("drive.delete")}
                        >
                          &times;
                        </button>
                      </div>
                    </div>
                  )}
                </For>
              </div>
            </div>
          </Show>
          <div class="compose-modal-body">
            <NoteComposer
              key={resetKey()}
              onPost={handlePost}
              replyTo={props.replyTo}
              quoteNote={props.quoteNote}
              initialContent={draftContent()}
              initialVisibility={draftVisibility()}
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
