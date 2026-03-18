import { createSignal, createEffect, Show } from "solid-js";
import {
  getRemoteEmojiInfo,
  importAndReact,
  type RemoteEmojiInfo,
} from "@nekonoverse/ui/api/statuses";
import EmojiEditForm, { type EmojiEditFields } from "./EmojiEditForm";
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
    setError("");
    getRemoteEmojiInfo(p.shortcode, p.domain)
      .then((info) => {
        setMeta(info);
        setFields({
          shortcode: info.shortcode,
          category: info.category || "",
          author: info.author || "",
          license: info.license || "",
          description: info.description || "",
          isSensitive: info.is_sensitive,
          aliases: (info.aliases || []).join(", "),
        });
      })
      .catch(() => setError(t("reactions.importFailed")))
      .finally(() => setLoading(false));
  });

  const buildBody = (react: boolean) => {
    const p = parsed()!;
    const f = fields();
    const emojiWithDomain = `:${p.shortcode}@${p.domain}:`;
    return {
      emoji: emojiWithDomain,
      shortcode: f.shortcode !== p.shortcode ? f.shortcode : undefined,
      category: f.category || undefined,
      author: f.author || undefined,
      license: f.license || undefined,
      description: f.description || undefined,
      is_sensitive: f.isSensitive,
      aliases: f.aliases
        ? f.aliases
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean)
        : undefined,
      react,
    };
  };

  const handleSubmit = async (react: boolean) => {
    if (isDenied() || submitting()) return;
    setSubmitting(true);
    setError("");
    try {
      await importAndReact(props.noteId, buildBody(react));
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
            {t("reactions.importEmojiTitle")}
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
