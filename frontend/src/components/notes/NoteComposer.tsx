import { createSignal, Show, For, onCleanup } from "solid-js";
import { createNote, uploadMedia, type Note, type MediaAttachment } from "../../api/statuses";
import { useI18n } from "../../i18n";
import DrivePicker from "../DrivePicker";
import { sanitizeHTML } from "../../utils/sanitize";
import type { DriveFile } from "../../api/drive";
import {
  getInitialVisibility,
  rememberVisibility,
  defaultVisibility,
  setLastVisibility,
  type Visibility,
} from "../../stores/composer";

const VISIBILITY_OPTIONS: { key: Visibility; emoji: string; i18nKey: string }[] = [
  { key: "public", emoji: "\u{1F310}", i18nKey: "visibility.public" },
  { key: "unlisted", emoji: "\u{1F513}", i18nKey: "visibility.unlisted" },
  { key: "followers", emoji: "\u{1F512}", i18nKey: "visibility.followers" },
  { key: "direct", emoji: "\u2709\uFE0F", i18nKey: "visibility.direct" },
];

const MAX_FILES = 4;

interface Props {
  onPost?: (note: Note) => void;
  quoteNote?: Note | null;
  onClearQuote?: () => void;
}

export default function NoteComposer(props: Props) {
  const { t } = useI18n();
  const [content, setContent] = createSignal("");
  const [visibility, setVisibility] = createSignal<Visibility>(getInitialVisibility());
  const [loading, setLoading] = createSignal(false);
  const [error, setError] = createSignal("");
  const [attachments, setAttachments] = createSignal<MediaAttachment[]>([]);
  const [uploading, setUploading] = createSignal(false);
  const [visMenuOpen, setVisMenuOpen] = createSignal(false);
  const [drivePickerOpen, setDrivePickerOpen] = createSignal(false);

  let fileInput!: HTMLInputElement;

  const visEmoji = () => VISIBILITY_OPTIONS.find((o) => o.key === visibility())?.emoji || "\u{1F310}";

  // Close visibility menu on outside click
  const handleDocClick = (e: MouseEvent) => {
    if (!(e.target as HTMLElement).closest(".composer-vis-wrap")) {
      setVisMenuOpen(false);
    }
  };
  if (typeof document !== "undefined") {
    document.addEventListener("click", handleDocClick);
    onCleanup(() => document.removeEventListener("click", handleDocClick));
  }

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const remaining = MAX_FILES - attachments().length;
    if (remaining <= 0) return;

    setUploading(true);
    setError("");
    const toUpload = Array.from(files).slice(0, remaining);

    for (const file of toUpload) {
      try {
        const media = await uploadMedia(file);
        setAttachments((prev) => [...prev, media]);
      } catch (err) {
        setError(err instanceof Error ? err.message : t("composer.uploadFailed"));
        break;
      }
    }
    setUploading(false);
    if (fileInput) fileInput.value = "";
  };

  const removeAttachment = (id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  };

  const handleDriveSelect = (driveFiles: DriveFile[]) => {
    setDrivePickerOpen(false);
    const remaining = MAX_FILES - attachments().length;
    const toAdd = driveFiles.slice(0, remaining);
    const newAttachments: MediaAttachment[] = toAdd.map((f) => ({
      id: f.id,
      type: f.mime_type.startsWith("image/") ? "image" : "unknown",
      url: f.url,
      preview_url: f.url,
      description: f.description,
      blurhash: f.blurhash,
      meta: f.width && f.height ? { original: { width: f.width, height: f.height } } : null,
    }));
    setAttachments((prev) => [...prev, ...newAttachments]);
  };

  const handleSubmit = async (e: Event) => {
    e.preventDefault();
    if (!content().trim() && attachments().length === 0) return;
    setLoading(true);
    setError("");
    try {
      const mediaIds = attachments().map((a) => a.id);
      const quoteId = props.quoteNote?.id;
      const note = await createNote(content(), visibility(), mediaIds.length > 0 ? mediaIds : undefined, quoteId);
      setContent("");
      setAttachments([]);
      props.onClearQuote?.();

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

  const handlePaste = (e: ClipboardEvent) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    const files: File[] = [];
    for (const item of items) {
      if (item.kind === "file" && item.type.startsWith("image/")) {
        const file = item.getAsFile();
        if (file) files.push(file);
      }
    }
    if (files.length > 0) {
      e.preventDefault();
      const dt = new DataTransfer();
      files.forEach((f) => dt.items.add(f));
      handleFiles(dt.files);
    }
  };

  return (
    <form onSubmit={handleSubmit} class="note-composer">
      {error() && <div class="error">{error()}</div>}
      <Show when={props.quoteNote}>
        {(qn) => (
          <div class="composer-quote-preview">
            <div class="composer-quote-header">
              <span class="composer-quote-label">{t("boost.quoting")}</span>
              <button type="button" class="composer-quote-close" onClick={() => props.onClearQuote?.()}>✕</button>
            </div>
            <div class="composer-quote-body">
              <strong>{qn().actor.display_name || qn().actor.username}</strong>
              <div class="composer-quote-text" innerHTML={sanitizeHTML(qn().content)} />
            </div>
          </div>
        )}
      </Show>
      <textarea
        value={content()}
        onInput={(e) => setContent(e.currentTarget.value)}
        onPaste={handlePaste}
        placeholder={t("composer.placeholder")}
        rows={3}
        maxLength={5000}
      />
      <Show when={attachments().length > 0}>
        <div class="composer-media-preview">
          <For each={attachments()}>
            {(media) => (
              <div class="composer-media-item">
                <img src={media.preview_url} alt={media.description || ""} />
                <button
                  type="button"
                  class="composer-media-remove"
                  onClick={() => removeAttachment(media.id)}
                >
                  ✕
                </button>
              </div>
            )}
          </For>
        </div>
      </Show>
      <div class="composer-footer">
        <div class="composer-footer-left">
          <button
            type="button"
            class="composer-attach-btn"
            onClick={() => fileInput.click()}
            disabled={uploading() || attachments().length >= MAX_FILES}
            title={t("composer.attach")}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
              <circle cx="8.5" cy="8.5" r="1.5" />
              <polyline points="21 15 16 10 5 21" />
            </svg>
            <Show when={uploading()}>
              <span class="composer-uploading">...</span>
            </Show>
          </button>
          <button
            type="button"
            class="composer-attach-btn"
            onClick={() => setDrivePickerOpen(true)}
            disabled={attachments().length >= MAX_FILES}
            title={t("drive.pickFromDrive")}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            </svg>
          </button>
          <input
            ref={fileInput}
            type="file"
            accept="image/jpeg,image/png,image/gif,image/webp"
            multiple
            onChange={(e) => handleFiles(e.currentTarget.files)}
            style="display: none"
          />
        </div>
        <div class="composer-actions">
          <span class="char-count">{content().length} / 5000</span>
          <div class="composer-vis-wrap">
            <div class="composer-post-group">
              <button
                type="submit"
                class="composer-post-btn"
                disabled={loading() || (!content().trim() && attachments().length === 0)}
              >
                {loading() ? t("composer.posting") : t("composer.post")}
                <span class="composer-vis-icon">{visEmoji()}</span>
              </button>
              <button
                type="button"
                class="composer-vis-toggle"
                onClick={(e) => { e.stopPropagation(); setVisMenuOpen(!visMenuOpen()); }}
              >
                ▲
              </button>
            </div>
            <Show when={visMenuOpen()}>
              <div class="composer-vis-dropdown">
                <For each={VISIBILITY_OPTIONS}>
                  {(opt) => (
                    <button
                      type="button"
                      class={`composer-vis-item${visibility() === opt.key ? " active" : ""}`}
                      onClick={() => { setVisibility(opt.key); setVisMenuOpen(false); }}
                    >
                      <span>{opt.emoji}</span> {t(opt.i18nKey as any)}
                    </button>
                  )}
                </For>
              </div>
            </Show>
          </div>
        </div>
      </div>
      <Show when={drivePickerOpen()}>
        <DrivePicker
          maxSelect={MAX_FILES - attachments().length}
          onSelect={handleDriveSelect}
          onClose={() => setDrivePickerOpen(false)}
        />
      </Show>
    </form>
  );
}
