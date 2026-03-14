import { createSignal, createEffect, Show, For, onCleanup } from "solid-js";
import { createNote, uploadMedia, updateMedia, type Note, type MediaAttachment, type PollCreate } from "@nekonoverse/ui/api/statuses";
import { useI18n } from "@nekonoverse/ui/i18n";
import DrivePicker from "../DrivePicker";
import FocalPointPicker from "../FocalPointPicker";
import EmojiPicker from "../reactions/EmojiPicker";
import { sanitizeHtml } from "@nekonoverse/ui/utils/sanitize";
import { stripExifFromFile } from "@nekonoverse/ui/utils/stripExif";
import type { DriveFile } from "@nekonoverse/ui/api/drive";
import {
  getInitialVisibility,
  rememberVisibility,
  defaultVisibility,
  setLastVisibility,
  type Visibility,
} from "@nekonoverse/ui/stores/composer";

const VISIBILITY_OPTIONS: { key: Visibility; emoji: string; i18nKey: string }[] = [
  { key: "public", emoji: "\u{1F310}", i18nKey: "visibility.public" },
  { key: "unlisted", emoji: "\u{1F513}", i18nKey: "visibility.unlisted" },
  { key: "followers", emoji: "\u{1F512}", i18nKey: "visibility.followers" },
  { key: "direct", emoji: "\u2709\uFE0F", i18nKey: "visibility.direct" },
];

const MAX_FILES = 4;
const MIN_POLL_OPTIONS = 2;
const MAX_POLL_OPTIONS = 4;
const POLL_EXPIRY_OPTIONS = [
  { value: 300, i18nKey: "poll.expires5m" },
  { value: 1800, i18nKey: "poll.expires30m" },
  { value: 3600, i18nKey: "poll.expires1h" },
  { value: 21600, i18nKey: "poll.expires6h" },
  { value: 86400, i18nKey: "poll.expires1d" },
  { value: 259200, i18nKey: "poll.expires3d" },
  { value: 604800, i18nKey: "poll.expires7d" },
];

interface Props {
  onPost?: (note: Note) => void;
  quoteNote?: Note | null;
  onClearQuote?: () => void;
  replyTo?: Note | null;
  onClearReply?: () => void;
  /** Increment to reset the form */
  key?: number;
  /** Called when content or visibility changes */
  onContentChange?: (content: string, visibility: Visibility) => void;
  /** Initial content for draft restore */
  initialContent?: string;
  /** Initial visibility for draft restore */
  initialVisibility?: Visibility;
  /** Called when upload state changes */
  onUploadingChange?: (uploading: boolean) => void;
  /** External files dropped on parent (e.g. modal) */
  externalFiles?: FileList | null;
}

export default function NoteComposer(props: Props) {
  const { t } = useI18n();
  const [content, setContent] = createSignal(props.initialContent || "");
  const [visibility, setVisibility] = createSignal<Visibility>(props.initialVisibility || getInitialVisibility());
  const [loading, setLoading] = createSignal(false);
  const [error, setError] = createSignal("");
  const [attachments, setAttachments] = createSignal<MediaAttachment[]>([]);
  const [uploading, setUploading] = createSignal(false);
  const [visMenuOpen, setVisMenuOpen] = createSignal(false);
  const [drivePickerOpen, setDrivePickerOpen] = createSignal(false);
  const [focalPickerMedia, setFocalPickerMedia] = createSignal<MediaAttachment | null>(null);
  const [emojiPickerOpen, setEmojiPickerOpen] = createSignal(false);
  const [dragging, setDragging] = createSignal(false);
  const [pollOpen, setPollOpen] = createSignal(false);
  const [pollOptions, setPollOptions] = createSignal<string[]>(["", ""]);
  const [pollMultiple, setPollMultiple] = createSignal(false);
  const [pollExpiresIn, setPollExpiresIn] = createSignal(86400);

  let fileInput!: HTMLInputElement;
  let textareaRef!: HTMLTextAreaElement;

  // Auto-set visibility and prepend @mention when replying
  createEffect(() => {
    if (props.replyTo) {
      const parentVis = props.replyTo.visibility as Visibility;
      if (VISIBILITY_OPTIONS.some((o) => o.key === parentVis)) {
        setVisibility(parentVis);
      }
      // Auto-prepend @mention for the replied-to user
      const actor = props.replyTo.actor;
      if (actor && !content()) {
        const mention = actor.domain
          ? `@${actor.username}@${actor.domain} `
          : `@${actor.username} `;
        setContent(mention);
      }
    }
  });

  // Reset form when key changes (modal re-opened)
  createEffect(() => {
    const _key = props.key;
    if (_key !== undefined && _key > 0) {
      setContent(props.initialContent || "");
      setVisibility(props.initialVisibility || getInitialVisibility());
      setAttachments([]);
      setError("");
      setPollOpen(false);
      setPollOptions(["", ""]);
      setPollMultiple(false);
      setPollExpiresIn(86400);
    }
  });

  // Report content changes to parent
  createEffect(() => {
    props.onContentChange?.(content(), visibility());
  });

  // Report upload state to parent
  createEffect(() => {
    props.onUploadingChange?.(uploading());
  });

  // Handle files dropped on parent (e.g. modal wrapper)
  createEffect(() => {
    const files = props.externalFiles;
    if (files && files.length > 0) {
      handleFiles(files);
    }
  });

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
        // Strip EXIF metadata (GPS, camera info, etc.) from images before upload
        const processed = await stripExifFromFile(file);
        const media = await uploadMedia(processed);
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

  const handleFocalSave = async (x: number, y: number) => {
    const media = focalPickerMedia();
    if (!media) return;
    try {
      const updated = await updateMedia(media.id, undefined, `${x},${y}`);
      setAttachments((prev) => prev.map((a) => a.id === media.id ? updated : a));
    } catch {
      // silent — focal point is optional
    }
    setFocalPickerMedia(null);
  };

  const handleDriveSelect = (driveFiles: DriveFile[]) => {
    setDrivePickerOpen(false);
    const remaining = MAX_FILES - attachments().length;
    const toAdd = driveFiles.slice(0, remaining);
    const newAttachments: MediaAttachment[] = toAdd.map((f) => {
      const meta: MediaAttachment["meta"] = f.width && f.height
        ? { original: { width: f.width, height: f.height } }
        : null;
      if (f.focal_x != null && f.focal_y != null) {
        const m = meta || {};
        m.focus = { x: f.focal_x, y: f.focal_y };
        return {
          id: f.id, type: f.mime_type.startsWith("image/") ? "image" : "unknown",
          url: f.url, preview_url: f.url, description: f.description,
          blurhash: f.blurhash, meta: m,
        };
      }
      return {
        id: f.id, type: f.mime_type.startsWith("image/") ? "image" : "unknown",
        url: f.url, preview_url: f.url, description: f.description,
        blurhash: f.blurhash, meta,
      };
    });
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
      const replyToId = props.replyTo?.id;
      let pollData: PollCreate | undefined;
      if (pollOpen()) {
        const opts = pollOptions().filter((o) => o.trim());
        if (opts.length >= MIN_POLL_OPTIONS) {
          pollData = {
            options: opts,
            expires_in: pollExpiresIn(),
            multiple: pollMultiple(),
          };
        }
      }
      const note = await createNote(
        content(),
        visibility(),
        mediaIds.length > 0 ? mediaIds : undefined,
        quoteId,
        replyToId,
        pollData,
      );
      setContent("");
      setAttachments([]);
      setPollOpen(false);
      setPollOptions(["", ""]);
      setPollMultiple(false);
      setPollExpiresIn(86400);
      props.onClearQuote?.();
      props.onClearReply?.();

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

  const handleEmojiSelect = (emoji: string) => {
    const textarea = textareaRef;
    const start = textarea?.selectionStart ?? content().length;
    const end = textarea?.selectionEnd ?? content().length;
    const before = content().slice(0, start);
    const after = content().slice(end);
    setContent(before + emoji + after);
    setEmojiPickerOpen(false);
    // カーソルを挿入した絵文字の後ろに移動
    requestAnimationFrame(() => {
      if (textarea) {
        const pos = start + emoji.length;
        textarea.selectionStart = pos;
        textarea.selectionEnd = pos;
        textarea.focus();
      }
    });
  };

  const replyToActor = () => {
    const rt = props.replyTo;
    if (!rt) return null;
    return rt.actor;
  };

  return (
    <form
      onSubmit={handleSubmit}
      class={`note-composer${dragging() ? " drag-over" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        if (e.dataTransfer?.files?.length) handleFiles(e.dataTransfer.files);
      }}
    >
      {error() && <div class="error">{error()}</div>}
      <Show when={replyToActor()}>
        {(actor) => (
          <div class="composer-reply-indicator">
            <span class="composer-reply-label">
              {t("reply.replyingTo")} @{actor().username}{actor().domain ? `@${actor().domain}` : ""}
            </span>
            <Show when={props.onClearReply}>
              <button type="button" class="composer-reply-close" onClick={() => props.onClearReply?.()}>
                ✕
              </button>
            </Show>
          </div>
        )}
      </Show>
      <Show when={props.quoteNote}>
        {(qn) => (
          <div class="composer-quote-preview">
            <div class="composer-quote-header">
              <span class="composer-quote-label">{t("boost.quoting")}</span>
              <button type="button" class="composer-quote-close" onClick={() => props.onClearQuote?.()}>✕</button>
            </div>
            <div class="composer-quote-body">
              <strong>{qn().actor.display_name || qn().actor.username}</strong>
              <div class="composer-quote-text" innerHTML={sanitizeHtml(qn().content)} />
            </div>
          </div>
        )}
      </Show>
      <textarea
        ref={textareaRef}
        value={content()}
        onInput={(e) => setContent(e.currentTarget.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !uploading()) {
            handleSubmit(e);
          }
        }}
        onPaste={handlePaste}
        placeholder={props.replyTo ? t("reply.reply") + "..." : t("composer.placeholder")}
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
                  class="composer-media-focal-btn"
                  onClick={() => setFocalPickerMedia(media)}
                  title={t("composer.setFocalPoint")}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="3" />
                    <line x1="12" y1="2" x2="12" y2="6" />
                    <line x1="12" y1="18" x2="12" y2="22" />
                    <line x1="2" y1="12" x2="6" y2="12" />
                    <line x1="18" y1="12" x2="22" y2="12" />
                  </svg>
                </button>
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
      <Show when={pollOpen()}>
        <div class="composer-poll-editor">
          <For each={pollOptions()}>
            {(opt, i) => (
              <div class="composer-poll-option">
                <input
                  type="text"
                  class="composer-poll-input"
                  value={opt}
                  onInput={(e) => {
                    const newOpts = [...pollOptions()];
                    newOpts[i()] = e.currentTarget.value;
                    setPollOptions(newOpts);
                  }}
                  placeholder={`${t("poll.option" as any)} ${i() + 1}`}
                  maxLength={50}
                />
                <Show when={pollOptions().length > MIN_POLL_OPTIONS}>
                  <button
                    type="button"
                    class="composer-poll-remove"
                    onClick={() => {
                      const newOpts = pollOptions().filter((_, idx) => idx !== i());
                      setPollOptions(newOpts);
                    }}
                  >
                    ✕
                  </button>
                </Show>
              </div>
            )}
          </For>
          <Show when={pollOptions().length < MAX_POLL_OPTIONS}>
            <button
              type="button"
              class="composer-poll-add"
              onClick={() => setPollOptions([...pollOptions(), ""])}
            >
              + {t("poll.addOption" as any)}
            </button>
          </Show>
          <div class="composer-poll-settings">
            <label class="composer-poll-multiple">
              <input
                type="checkbox"
                checked={pollMultiple()}
                onChange={(e) => setPollMultiple(e.currentTarget.checked)}
              />
              {t("poll.multiple" as any)}
            </label>
            <select
              class="composer-poll-expiry"
              value={pollExpiresIn()}
              onChange={(e) => setPollExpiresIn(Number(e.currentTarget.value))}
            >
              <For each={POLL_EXPIRY_OPTIONS}>
                {(opt) => (
                  <option value={opt.value}>{t(opt.i18nKey as any)}</option>
                )}
              </For>
            </select>
          </div>
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
          <div class="composer-emoji-wrap">
            <button
              type="button"
              class="composer-attach-btn"
              onClick={() => {
                const opening = !emojiPickerOpen();
                if (opening) textareaRef?.blur();
                setEmojiPickerOpen(opening);
              }}
              title={t("composer.emoji" as any)}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10" />
                <path d="M8 14s1.5 2 4 2 4-2 4-2" />
                <line x1="9" y1="9" x2="9.01" y2="9" />
                <line x1="15" y1="9" x2="15.01" y2="9" />
              </svg>
            </button>
            <Show when={emojiPickerOpen()}>
              <div class="composer-emoji-backdrop" onClick={() => setEmojiPickerOpen(false)} />
              <EmojiPicker
                onSelect={handleEmojiSelect}
                onClose={() => setEmojiPickerOpen(false)}
              />
            </Show>
          </div>
          <button
            type="button"
            class={`composer-attach-btn${pollOpen() ? " active" : ""}`}
            onClick={() => setPollOpen(!pollOpen())}
            title={t("poll.create" as any)}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="3" width="18" height="4" rx="1" />
              <rect x="3" y="10" width="12" height="4" rx="1" />
              <rect x="3" y="17" width="15" height="4" rx="1" />
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
                disabled={loading() || uploading() || (!content().trim() && attachments().length === 0)}
              >
                {uploading() ? t("composer.uploading") : loading() ? t("composer.posting") : (props.replyTo ? t("reply.reply") : t("composer.post"))}
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
      <Show when={focalPickerMedia()}>
        {(media) => (
          <FocalPointPicker
            imageUrl={media().url}
            initialX={media().meta?.focus?.x}
            initialY={media().meta?.focus?.y}
            onSave={handleFocalSave}
            onClose={() => setFocalPickerMedia(null)}
          />
        )}
      </Show>
    </form>
  );
}
