import { createSignal, createEffect, Show, For, onCleanup } from "solid-js";
import { useNavigate } from "@solidjs/router";
import type { ReactionUser } from "@nekonoverse/ui/api/statuses";
import { reactToNote, unreactToNote, getReactedBy } from "@nekonoverse/ui/api/statuses";
import type { ReactionSummary } from "@nekonoverse/ui/api/statuses";
import { computePhash } from "@nekonoverse/ui/utils/phash";
import { groupReactions, type GroupedReaction } from "@nekonoverse/ui/utils/groupReactions";
import { getAllCachedPhashes, setCachedPhash } from "@nekonoverse/ui/utils/phashCache";
import EmojiPicker from "./EmojiPicker";
import EmojiImportModal from "./EmojiImportModal";
import Emoji from "../Emoji";
import { canManageEmoji } from "@nekonoverse/ui/stores/auth";
import { importedShortcodes } from "@nekonoverse/ui/api/emoji";
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
  const [modalUrl, setModalUrl] = createSignal<string | null>(null);
  const [modalUsers, setModalUsers] = createSignal<ReactionUser[]>([]);
  const [modalLoading, setModalLoading] = createSignal(false);
  const [importEmoji, setImportEmoji] = createSignal<string | null>(null);
  const [importDomain, setImportDomain] = createSignal<string | null>(null);

  let longPressTimer: ReturnType<typeof setTimeout> | null = null;
  let didLongPress = false;

  // pHash-based grouping
  const [hashMap, setHashMap] = createSignal<Map<string, string>>(
    getAllCachedPhashes(),
  );

  const SHORTCODE_RE = /^:([a-zA-Z0-9_]+)(?:@[^:]+)?:$/;

  const grouped = (): GroupedReaction[] => {
    const groups = groupReactions(props.reactions, hashMap());
    const imported = importedShortcodes();
    if (imported.size === 0) return groups;
    return groups.map((g) => {
      const m = SHORTCODE_RE.exec(g.displayEmoji);
      if (m && imported.has(m[1])) {
        return { ...g, importable: false, importDomain: null };
      }
      return g;
    });
  };

  // Compute pHash for uncached custom emoji URLs
  createEffect(() => {
    const currentMap = hashMap();
    const urlsToHash: string[] = [];

    for (const r of props.reactions) {
      if (r.emoji_url && !currentMap.has(r.emoji_url)) {
        urlsToHash.push(r.emoji_url);
      }
    }

    if (urlsToHash.length === 0) return;

    Promise.all(
      urlsToHash.map(async (url) => {
        const hash = await computePhash(url);
        return hash ? { url, hash } : null;
      }),
    ).then((results) => {
      const newEntries = results.filter(
        (r): r is { url: string; hash: string } => r !== null,
      );
      if (newEntries.length === 0) return;

      setHashMap((prev) => {
        const next = new Map(prev);
        for (const { url, hash } of newEntries) {
          next.set(url, hash);
          setCachedPhash(url, hash);
        }
        return next;
      });
    });
  });

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

  const handleReaction = (group: GroupedReaction) => {
    if (didLongPress) return;
    if (group.importable) {
      if (canManageEmoji()) {
        setImportEmoji(group.displayEmoji);
        setImportDomain(group.importDomain);
      }
      return;
    }
    const emojiToUse =
      group.me && group.myEmoji ? group.myEmoji : group.displayEmoji;
    toggleReaction(emojiToUse);
  };

  const openModal = async (group: GroupedReaction) => {
    setModalEmoji(group.displayEmoji);
    setModalUrl(group.displayUrl);
    setModalLoading(true);
    try {
      const allUsers = await Promise.all(
        group.members.map((m) => getReactedBy(props.noteId, m.emoji)),
      );
      const seen = new Set<string>();
      const uniqueUsers: ReactionUser[] = [];
      for (const users of allUsers) {
        for (const u of users) {
          if (!seen.has(u.actor.id)) {
            seen.add(u.actor.id);
            uniqueUsers.push(u);
          }
        }
      }
      setModalUsers(uniqueUsers);
    } catch {
      setModalUsers([]);
    }
    setModalLoading(false);
  };

  const closeModal = () => {
    setModalEmoji(null);
    setModalUrl(null);
    setModalUsers([]);
    didLongPress = false;
  };

  const startLongPress = (group: GroupedReaction) => {
    didLongPress = false;
    longPressTimer = setTimeout(() => {
      didLongPress = true;
      openModal(group);
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

  const badgeClass = (group: GroupedReaction) => {
    let cls = "reaction-badge";
    if (group.me) cls += " reaction-me";
    if (group.importable) {
      cls += canManageEmoji()
        ? " reaction-importable"
        : " reaction-remote-disabled";
    }
    return cls;
  };

  return (
    <>
      <div class="reaction-bar">
        {grouped().map((g) => (
          <button
            class={badgeClass(g)}
            onClick={() => handleReaction(g)}
            onMouseDown={() => startLongPress(g)}
            onMouseUp={cancelLongPress}
            onMouseLeave={cancelLongPress}
            onTouchStart={() => startLongPress(g)}
            onTouchEnd={(e) => { cancelLongPress(); if (didLongPress) { e.preventDefault(); } }}
            onContextMenu={(e) => e.preventDefault()}
          >
            <Emoji emoji={g.displayEmoji} url={g.displayUrl} /> {g.count}
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
                  url={modalUrl()}
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
