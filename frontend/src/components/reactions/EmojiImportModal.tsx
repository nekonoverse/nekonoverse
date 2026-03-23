import { createSignal, createEffect, Show } from "solid-js";
import {
  getRemoteEmojiSources,
  reactToNote,
  type RemoteEmojiInfo,
} from "@nekonoverse/ui/api/statuses";
import { importRemoteEmojiByShortcode } from "@nekonoverse/ui/api/admin";
import { clearEmojiCache, markShortcodeImported } from "@nekonoverse/ui/api/emoji";
import EmojiEditForm, { type EmojiEditFields } from "./EmojiEditForm";
import { useI18n } from "@nekonoverse/ui/i18n";

interface Props {
  emoji: string; // ":shortcode:" or ":shortcode@domain:"
  domain: string | null; // remote domain from reaction summary
  emojiUrl: string | null;
  noteId: string;
  onClose: () => void;
  onImported: () => void;
}

const CUSTOM_RE = /^:([a-zA-Z0-9_]+)(?:@([a-zA-Z0-9.-]+))?:$/;

export default function EmojiImportModal(props: Props) {
  const { t } = useI18n();
  const [sources, setSources] = createSignal<RemoteEmojiInfo[]>([]);
  const [sourceIndex, setSourceIndex] = createSignal(0);
  const [loading, setLoading] = createSignal(true);
  const [submitting, setSubmitting] = createSignal(false);
  const [error, setError] = createSignal("");

  const [fields, setFields] = createSignal<EmojiEditFields>({
    shortcode: "",
    category: "",
    author: "",
    license: "",
    description: "",
    isSensitive: false,
    aliases: "",
  });

  const parsed = () => {
    const m = CUSTOM_RE.exec(props.emoji);
    if (!m) return null;
    const domain = m[2] || props.domain;
    return domain ? { shortcode: m[1], domain } : null;
  };

  const meta = () => sources()[sourceIndex()] ?? null;
  const isDenied = () => meta()?.copy_permission === "deny";

  // Find domains that deny copying
  const denyDomains = () =>
    sources()
      .filter((s) => s.copy_permission === "deny")
      .map((s) => s.domain)
      .filter(Boolean) as string[];

  // Show warning when another source has deny but current source is not the deny one
  const denyWarning = () => {
    const deny = denyDomains();
    if (deny.length === 0) return null;
    const current = meta();
    if (!current || deny.includes(current.domain!)) return null;
    const domain = deny[0];
    return t("reactions.copyViolationWarning").replace("{domain}", domain);
  };

  const applySourceFields = (info: RemoteEmojiInfo) => {
    setFields({
      shortcode: info.shortcode,
      category: info.category || "",
      author: info.author || "",
      license: info.license || "",
      description: info.description || "",
      isSensitive: info.is_sensitive,
      aliases: (info.aliases || []).join(", "),
    });
  };

  // Fetch all sources on mount
  createEffect(() => {
    const p = parsed();
    if (!p) {
      setLoading(false);
      setError(t("reactions.importFailed"));
      return;
    }
    setLoading(true);
    setError("");
    getRemoteEmojiSources(p.shortcode)
      .then((list) => {
        if (list.length === 0) {
          setError(t("reactions.importFailed"));
          return;
        }
        setSources(list);
        // Start with the domain from props if available
        const idx = list.findIndex((s) => s.domain === p.domain);
        const startIdx = idx >= 0 ? idx : 0;
        setSourceIndex(startIdx);
        applySourceFields(list[startIdx]);
      })
      .catch(() => setError(t("reactions.importFailed")))
      .finally(() => setLoading(false));
  });

  const goToPrev = () => {
    const idx = (sourceIndex() - 1 + sources().length) % sources().length;
    setSourceIndex(idx);
    applySourceFields(sources()[idx]);
  };

  const goToNext = () => {
    const idx = (sourceIndex() + 1) % sources().length;
    setSourceIndex(idx);
    applySourceFields(sources()[idx]);
  };

  const handleSubmit = async (react: boolean) => {
    if (isDenied() || submitting()) return;
    setSubmitting(true);
    setError("");
    try {
      const current = meta()!;
      const f = fields();
      const parsedAliases = f.aliases
        ? f.aliases.split(",").map((s) => s.trim()).filter(Boolean)
        : undefined;
      const localShortcode = f.shortcode !== current.shortcode ? f.shortcode : current.shortcode;

      // Import via admin API
      await importRemoteEmojiByShortcode({
        shortcode: current.shortcode,
        domain: current.domain!,
        shortcode_override: f.shortcode !== current.shortcode ? f.shortcode : undefined,
        category: f.category || undefined,
        author: f.author || undefined,
        license: f.license || undefined,
        description: f.description || undefined,
        is_sensitive: f.isSensitive,
        aliases: parsedAliases,
      });

      // Mark shortcode as imported so all ReactionBars suppress importable
      markShortcodeImported(localShortcode);
      clearEmojiCache();

      // React with the local emoji if requested
      if (react) {
        await reactToNote(props.noteId, `:${localShortcode}:`);
      }

      props.onImported();
      props.onClose();
    } catch (e: any) {
      setError(e.message || t("reactions.importFailed"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div class="modal-overlay" onClick={props.onClose}>
      <div
        class="modal-content"
        style="max-width: 440px"
        onClick={(e) => e.stopPropagation()}
      >
        <div class="modal-header">
          <h3>{t("reactions.importEmojiTitle")}</h3>
          <button class="modal-close" onClick={props.onClose}>
            ✕
          </button>
        </div>

        <Show when={loading()}>
          <div style="padding: 24px; text-align: center; color: var(--text-secondary)">
            {t("common.loading")}
          </div>
        </Show>

        <Show when={!loading() && meta()}>
          <div class="emoji-import-form">
            {/* Source navigation */}
            <Show when={sources().length > 1}>
              <div class="emoji-source-nav">
                <button class="btn" onClick={goToPrev}>◀</button>
                <span class="emoji-source-info">
                  <strong>{meta()!.domain}</strong>
                  {" "}({sourceIndex() + 1} / {sources().length})
                </span>
                <button class="btn" onClick={goToNext}>▶</button>
              </div>
            </Show>

            <Show when={isDenied()}>
              <div class="emoji-import-denied">
                {t("reactions.importDenied")}
              </div>
            </Show>

            <Show when={denyWarning()}>
              <div class="emoji-import-warning">
                {denyWarning()}
              </div>
            </Show>

            <EmojiEditForm
              fields={fields()}
              onChange={setFields}
              previewUrl={meta()!.url}
              previewDomain={meta()!.domain}
            />

            <Show when={error()}>
              <div class="emoji-import-error">{error()}</div>
            </Show>

            <div class="emoji-import-actions">
              <button class="btn" onClick={props.onClose}>
                {t("common.cancel")}
              </button>
              <button
                class="btn"
                onClick={() => handleSubmit(false)}
                disabled={isDenied() || submitting()}
              >
                {submitting()
                  ? t("common.loading")
                  : t("reactions.importEmoji")}
              </button>
              <button
                class="btn btn-primary"
                onClick={() => handleSubmit(true)}
                disabled={isDenied() || submitting()}
              >
                {submitting()
                  ? t("common.loading")
                  : t("reactions.importAndReact")}
              </button>
            </div>
          </div>
        </Show>

        <Show when={!loading() && !meta() && error()}>
          <div style="padding: 24px; text-align: center; color: var(--error)">
            {error()}
          </div>
        </Show>
      </div>
    </div>
  );
}
