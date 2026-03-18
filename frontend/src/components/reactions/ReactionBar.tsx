import { createSignal, Show, For, onCleanup } from "solid-js";
import { useNavigate } from "@solidjs/router";
import type { ReactionSummary, ReactionUser } from "@nekonoverse/ui/api/statuses";
import { reactToNote, unreactToNote, getReactedBy } from "@nekonoverse/ui/api/statuses";
import EmojiPicker from "./EmojiPicker";
import EmojiImportModal from "./EmojiImportModal";
import Emoji from "../Emoji";
import { canManageEmoji } from "@nekonoverse/ui/stores/auth";
import { useI18n } from "@nekonoverse/ui/i18n";
import { defaultAvatar } from "@nekonoverse/ui/stores/instance";

interface Props {
  noteId: string;
  reactions: ReactionSummary[];
  onUpdate?: () => void;
  serverSoftware?: string | null;
}

export default function ReactionBar(props: Props) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [showPicker, setShowPicker] = createSignal(false);
  const [modalEmoji, setModalEmoji] = createSignal<string | null>(null);
  const [modalUsers, setModalUsers] = createSignal<ReactionUser[]>([]);
  const [modalLoading, setModalLoading] = createSignal(false);
  const [importEmoji, setImportEmoji] = createSignal<string | null>(null);
  const [importDomain, setImportDomain] = createSignal<string | null>(null);

  let longPressTimer: ReturnType<typeof setTimeout> | null = null;
  let didLongPress = false;

  const toggleReaction = async (emoji: string) => {
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

  const handleReaction = (emoji: string, r: ReactionSummary) => {
    if (didLongPress) return;
    // Importable remote emoji: open import modal for permitted users
    if (r.importable) {
      if (canManageEmoji()) {
        setImportEmoji(emoji);
        setImportDomain(r.import_domain ?? null);
      }
      // General users can't bandwagon with importable emojis (disabled via CSS)
      return;
    }
    toggleReaction(emoji);
  };

  const openModal = async (emoji: string) => {
    setModalEmoji(emoji);
    setModalLoading(true);
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
    didLongPress = false;
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

  const ignoresReactions = () => props.serverSoftware === "mastodon";

  const badgeClass = (r: ReactionSummary) => {
    let cls = "reaction-badge";
    if (r.me) cls += " reaction-me";
    if (r.importable) {
      cls += canManageEmoji()
        ? " reaction-importable"
        : " reaction-remote-disabled";
    }
    return cls;
  };

  return (
    <>
      <div class="reaction-bar">
        {props.reactions.map((r) => (
          <button
            class={badgeClass(r)}
            onClick={() => handleReaction(r.emoji, r)}
            onMouseDown={() => startLongPress(r.emoji)}
            onMouseUp={cancelLongPress}
            onMouseLeave={cancelLongPress}
            onTouchStart={() => startLongPress(r.emoji)}
            onTouchEnd={(e) => { cancelLongPress(); if (didLongPress) { e.preventDefault(); } }}
            onContextMenu={(e) => e.preventDefault()}
          >
            <Emoji emoji={r.emoji} url={r.emoji_url} /> {r.count}
          </button>
        ))}
        <button
          class={`reaction-add-btn${ignoresReactions() ? " reaction-not-delivered" : ""}`}
          onClick={() => {
            const opening = !showPicker();
            if (opening) (document.activeElement as HTMLElement)?.blur();
            setShowPicker(opening);
          }}
          title={ignoresReactions() ? t("reactions.notDelivered" as any) : undefined}
        >
          +
        </button>
        <Show when={showPicker()}>
          <div class="reaction-emoji-backdrop" onClick={() => setShowPicker(false)} />
          <EmojiPicker
            onSelect={(emoji) => toggleReaction(emoji)}
            onClose={() => setShowPicker(false)}
            usedEmojis={props.reactions.filter((r) => r.me).map((r) => r.emoji)}
          />
        </Show>
      </div>

      {/* Emoji import modal */}
      <Show when={importEmoji()}>
        <EmojiImportModal
          emoji={importEmoji()!}
          domain={importDomain()}
          emojiUrl={props.reactions.find((r) => r.emoji === importEmoji())?.emoji_url ?? null}
          noteId={props.noteId}
          onClose={() => { setImportEmoji(null); setImportDomain(null); }}
          onImported={() => props.onUpdate?.()}
        />
      </Show>

      {/* Reaction users modal (long press) */}
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
              <button class="modal-close" onClick={closeModal}>✕</button>
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
                        src={ru.actor.avatar_url || defaultAvatar()}
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
