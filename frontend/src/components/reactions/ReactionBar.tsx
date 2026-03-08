import { createSignal, Show, For, onCleanup } from "solid-js";
import { useNavigate } from "@solidjs/router";
import type { ReactionSummary, ReactionUser } from "../../api/statuses";
import { reactToNote, unreactToNote, getReactedBy } from "../../api/statuses";
import { importRemoteEmojiByShortcode } from "../../api/admin";
import EmojiPicker from "./EmojiPicker";
import Emoji from "../Emoji";
import { currentUser } from "../../stores/auth";
import { useI18n } from "../../i18n";

const REMOTE_EMOJI_RE = /^:([a-zA-Z0-9_]+)@([a-zA-Z0-9.-]+):$/;

interface Props {
  noteId: string;
  reactions: ReactionSummary[];
  onUpdate?: () => void;
}

export default function ReactionBar(props: Props) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [showPicker, setShowPicker] = createSignal(false);
  const [modalEmoji, setModalEmoji] = createSignal<string | null>(null);
  const [modalUsers, setModalUsers] = createSignal<ReactionUser[]>([]);
  const [modalLoading, setModalLoading] = createSignal(false);
  const [importState, setImportState] = createSignal<"idle" | "loading" | "success" | "error">("idle");
  const [importError, setImportError] = createSignal("");

  let longPressTimer: ReturnType<typeof setTimeout> | null = null;
  let didLongPress = false;

  const handleReaction = async (emoji: string) => {
    if (didLongPress) return;
    const existing = props.reactions.find((r) => r.emoji === emoji && r.me);
    try {
      if (existing) {
        await unreactToNote(props.noteId, emoji);
      } else {
        await reactToNote(props.noteId, emoji);
      }
      props.onUpdate?.();
    } catch {
      // ignore
    }
  };

  const importableEmoji = () => {
    const emoji = modalEmoji();
    if (!emoji) return null;
    const m = REMOTE_EMOJI_RE.exec(emoji);
    if (!m) return null;
    return { shortcode: m[1], domain: m[2] };
  };

  const handleImport = async () => {
    const parsed = importableEmoji();
    if (!parsed) return;
    setImportState("loading");
    try {
      await importRemoteEmojiByShortcode(parsed.shortcode, parsed.domain);
      setImportState("success");
    } catch (e: any) {
      setImportState("error");
      setImportError(e.message || t("reactions.importFailed"));
    }
  };

  const openModal = async (emoji: string) => {
    setModalEmoji(emoji);
    setModalLoading(true);
    setImportState("idle");
    setImportError("");
    try {
      const users = await getReactedBy(props.noteId, emoji);
      setModalUsers(users);
    } catch {
      setModalUsers([]);
    }
    setModalLoading(false);
  };

  const closeModal = () => {
    setModalEmoji(null);
    setModalUsers([]);
  };

  const startLongPress = (emoji: string) => {
    didLongPress = false;
    longPressTimer = setTimeout(() => {
      didLongPress = true;
      openModal(emoji);
    }, 500);
  };

  const cancelLongPress = () => {
    if (longPressTimer) {
      clearTimeout(longPressTimer);
      longPressTimer = null;
    }
  };

  onCleanup(() => cancelLongPress());

  return (
    <>
      <div class="reaction-bar">
        {props.reactions.map((r) => (
          <button
            class={`reaction-badge ${r.me ? "reaction-me" : ""}`}
            onClick={() => handleReaction(r.emoji)}
            onMouseDown={() => startLongPress(r.emoji)}
            onMouseUp={cancelLongPress}
            onMouseLeave={cancelLongPress}
            onTouchStart={() => startLongPress(r.emoji)}
            onTouchEnd={() => { cancelLongPress(); if (didLongPress) { /* prevent click */ } }}
            onContextMenu={(e) => e.preventDefault()}
          >
            <Emoji emoji={r.emoji} url={r.emoji_url} /> {r.count}
          </button>
        ))}
        <button class="reaction-add-btn" onClick={() => setShowPicker(!showPicker())}>
          +
        </button>
        <Show when={showPicker()}>
          <EmojiPicker
            onSelect={(emoji) => handleReaction(emoji)}
            onClose={() => setShowPicker(false)}
            usedEmojis={props.reactions.filter((r) => r.me).map((r) => r.emoji)}
          />
        </Show>
      </div>

      {/* Reaction users modal */}
      <Show when={modalEmoji()}>
        <div class="modal-overlay" onClick={closeModal}>
          <div class="modal-content" style="max-width: 400px" onClick={(e) => e.stopPropagation()}>
            <div class="modal-header">
              <h3 style="display: flex; align-items: center; gap: 8px">
                <Emoji
                  emoji={modalEmoji()!}
                  url={props.reactions.find((r) => r.emoji === modalEmoji())?.emoji_url ?? null}
                />
                {t("reactions.reactedBy")}
              </h3>
              <div style="display: flex; align-items: center; gap: 8px">
                <Show when={currentUser()?.role === "admin" && importableEmoji()}>
                  <Show when={importState() === "idle"}>
                    <button class="btn btn-small" onClick={handleImport}>
                      {t("reactions.importEmoji")}
                    </button>
                  </Show>
                  <Show when={importState() === "loading"}>
                    <button class="btn btn-small" disabled>
                      {t("common.loading")}
                    </button>
                  </Show>
                  <Show when={importState() === "success"}>
                    <span class="import-success">{t("reactions.importSuccess")}</span>
                  </Show>
                  <Show when={importState() === "error"}>
                    <span class="import-error" title={importError()}>
                      {t("reactions.importFailed")}
                    </span>
                  </Show>
                </Show>
                <button class="modal-close" onClick={closeModal}>✕</button>
              </div>
            </div>
            <div class="reacted-by-list">
              <Show when={modalLoading()}>
                <div style="padding: 24px; text-align: center; color: var(--text-secondary)">
                  {t("common.loading")}
                </div>
              </Show>
              <Show when={!modalLoading() && modalUsers().length === 0}>
                <div style="padding: 24px; text-align: center; color: var(--text-secondary)">
                  —
                </div>
              </Show>
              <For each={modalUsers()}>
                {(ru) => {
                  const handle = ru.actor.domain
                    ? `@${ru.actor.username}@${ru.actor.domain}`
                    : `@${ru.actor.username}`;
                  return (
                    <button
                      class="reacted-by-item"
                      onClick={() => { closeModal(); navigate(`/${handle}`); }}
                    >
                      <img
                        class="reacted-by-avatar"
                        src={ru.actor.avatar_url || "/default-avatar.svg"}
                        alt=""
                      />
                      <div class="reacted-by-names">
                        <span class="reacted-by-display">{ru.actor.display_name || ru.actor.username}</span>
                        <span class="reacted-by-handle">{handle}</span>
                      </div>
                    </button>
                  );
                }}
              </For>
            </div>
          </div>
        </div>
      </Show>
    </>
  );
}
