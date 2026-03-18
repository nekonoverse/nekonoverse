import { createSignal, createEffect, Show } from "solid-js";
import {
  getRemoteEmojiInfo,
  importAndReact,
  type RemoteEmojiInfo,
} from "@nekonoverse/ui/api/statuses";
import Emoji from "../Emoji";
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
  const [meta, setMeta] = createSignal<RemoteEmojiInfo | null>(null);
  const [loading, setLoading] = createSignal(true);
  const [submitting, setSubmitting] = createSignal(false);
  const [error, setError] = createSignal("");

  // Form fields
  const [shortcode, setShortcode] = createSignal("");
  const [category, setCategory] = createSignal("");
  const [author, setAuthor] = createSignal("");
  const [license, setLicense] = createSignal("");
  const [description, setDescription] = createSignal("");
  const [isSensitive, setIsSensitive] = createSignal(false);
  const [aliases, setAliases] = createSignal("");

  const parsed = () => {
    const m = CUSTOM_RE.exec(props.emoji);
    if (!m) return null;
    // Domain from the emoji string takes priority, otherwise use the prop
    const domain = m[2] || props.domain;
    return domain ? { shortcode: m[1], domain } : null;
  };

  const isDenied = () => meta()?.copy_permission === "deny";

  // Fetch metadata on mount
  createEffect(() => {
    const p = parsed();
    if (!p) {
      setLoading(false);
      setError(t("reactions.importFailed"));
      return;
    }
    setLoading(true);
    getRemoteEmojiInfo(p.shortcode, p.domain)
      .then((info) => {
        setMeta(info);
        setShortcode(info.shortcode);
        setCategory(info.category || "");
        setAuthor(info.author || "");
        setLicense(info.license || "");
        setDescription(info.description || "");
        setIsSensitive(info.is_sensitive);
        setAliases((info.aliases || []).join(", "));
      })
      .catch(() => setError(t("reactions.importFailed")))
      .finally(() => setLoading(false));
  });

  const handleSubmit = async () => {
    if (isDenied() || submitting()) return;
    setSubmitting(true);
    setError("");
    try {
      const p = parsed()!;
      const emojiWithDomain = `:${p.shortcode}@${p.domain}:`;
      await importAndReact(props.noteId, {
        emoji: emojiWithDomain,
        shortcode: shortcode() !== p.shortcode ? shortcode() : undefined,
        category: category() || undefined,
        author: author() || undefined,
        license: license() || undefined,
        description: description() || undefined,
        is_sensitive: isSensitive(),
        aliases: aliases()
          ? aliases()
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean)
          : undefined,
      });
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
          <h3 style="display: flex; align-items: center; gap: 8px">
            <Emoji emoji={props.emoji} url={props.emojiUrl} />
            {t("reactions.importAndReact")}
          </h3>
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
            <Show when={isDenied()}>
              <div class="emoji-import-denied">
                {t("reactions.importDenied")}
              </div>
            </Show>

            <div class="emoji-import-preview">
              <img
                src={meta()!.url}
                alt={`:${meta()!.shortcode}:`}
                style="height: 64px"
              />
              <span class="emoji-import-domain">{meta()!.domain}</span>
            </div>

            <label class="emoji-import-field">
              <span>{t("reactions.emojiShortcode")}</span>
              <input
                type="text"
                value={shortcode()}
                onInput={(e) => setShortcode(e.currentTarget.value)}
                pattern="[a-zA-Z0-9_]+"
              />
            </label>

            <label class="emoji-import-field">
              <span>{t("reactions.emojiCategory")}</span>
              <input
                type="text"
                value={category()}
                onInput={(e) => setCategory(e.currentTarget.value)}
              />
            </label>

            <label class="emoji-import-field">
              <span>{t("reactions.emojiAuthor")}</span>
              <input
                type="text"
                value={author()}
                onInput={(e) => setAuthor(e.currentTarget.value)}
              />
            </label>

            <label class="emoji-import-field">
              <span>{t("reactions.emojiLicense")}</span>
              <input
                type="text"
                value={license()}
                onInput={(e) => setLicense(e.currentTarget.value)}
              />
            </label>

            <label class="emoji-import-field">
              <span>{t("reactions.emojiDescription")}</span>
              <input
                type="text"
                value={description()}
                onInput={(e) => setDescription(e.currentTarget.value)}
              />
            </label>

            <label class="emoji-import-field">
              <span>{t("reactions.emojiAliases")}</span>
              <input
                type="text"
                value={aliases()}
                onInput={(e) => setAliases(e.currentTarget.value)}
                placeholder="alias1, alias2"
              />
            </label>

            <label class="emoji-import-checkbox">
              <input
                type="checkbox"
                checked={isSensitive()}
                onChange={(e) => setIsSensitive(e.currentTarget.checked)}
              />
              {t("reactions.emojiSensitive")}
            </label>

            <Show when={error()}>
              <div class="emoji-import-error">{error()}</div>
            </Show>

            <div class="emoji-import-actions">
              <button class="btn" onClick={props.onClose}>
                {t("common.cancel")}
              </button>
              <button
                class="btn btn-primary"
                onClick={handleSubmit}
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
