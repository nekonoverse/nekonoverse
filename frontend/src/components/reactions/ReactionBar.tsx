import { createSignal, createEffect, Show, For, onCleanup } from "solid-js";
import { useNavigate } from "@solidjs/router";
import type { ReactionUser } from "@nekonoverse/ui/api/statuses";
import { reactToNote, unreactToNote, getReactedBy } from "@nekonoverse/ui/api/statuses";
import type { ReactionSummary } from "@nekonoverse/ui/api/statuses";
import { computePhash } from "@nekonoverse/ui/utils/phash";
import { groupReactions, extractShortcode, type GroupedReaction } from "@nekonoverse/ui/utils/groupReactions";
import { getAllCachedPhashes, setCachedPhash } from "@nekonoverse/ui/utils/phashCache";
import EmojiPicker from "./EmojiPicker";
import EmojiImportModal from "./EmojiImportModal";
import Emoji from "../Emoji";
import { canManageEmoji } from "@nekonoverse/ui/stores/auth";
import { importedShortcodes } from "@nekonoverse/ui/api/emoji";
import { useI18n } from "@nekonoverse/ui/i18n";
import { defaultAvatar } from "@nekonoverse/ui/stores/instance";
import { activateTouchGuard } from "../../utils/touchGuard";
import { isTouchMode } from "@nekonoverse/ui/stores/theme";

interface Props {
  noteId: string;
  reactions: ReactionSummary[];
  onUpdate?: () => void;
  serverSoftware?: string | null;
}

// Track in-flight phash computations to prevent duplicate work
const inFlightUrls = new Set<string>();

// Module-level state: preserve picker open/close across <For> re-creations
// (When a streaming reaction event replaces the note object, <For> destroys
//  and re-creates the component, resetting local signals.)
const openPickerNoteIds = new Set<string>();
// Reactive signal: number of currently open emoji pickers (used by Home.tsx
// to suppress the "new posts" banner while a picker is visible).
const [pickerOpenCount, setPickerOpenCount] = createSignal(0);
export { pickerOpenCount };

export default function ReactionBar(props: Props) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [showPicker, _setShowPicker] = createSignal(openPickerNoteIds.has(props.noteId));

  const setShowPicker = (v: boolean) => {
    if (v) openPickerNoteIds.add(props.noteId);
    else openPickerNoteIds.delete(props.noteId);
    _setShowPicker(v);
    setPickerOpenCount(openPickerNoteIds.size);
  };
  const [modalEmoji, setModalEmoji] = createSignal<string | null>(null);
  const [modalUrl, setModalUrl] = createSignal<string | null>(null);
  const [modalUsers, setModalUsers] = createSignal<ReactionUser[]>([]);
  const [modalLoading, setModalLoading] = createSignal(false);
  const [importEmoji, setImportEmoji] = createSignal<string | null>(null);
  const [importDomain, setImportDomain] = createSignal<string | null>(null);

  let longPressTimer: ReturnType<typeof setTimeout> | null = null;
  let didLongPress = false;

  // Hover popover (PC mode)
  const [hoverGroup, setHoverGroup] = createSignal<GroupedReaction | null>(null);
  const [hoverUsers, setHoverUsers] = createSignal<ReactionUser[]>([]);
  const [hoverLoading, setHoverLoading] = createSignal(false);
  let hoverShowTimer: ReturnType<typeof setTimeout> | null = null;
  let hoverHideTimer: ReturnType<typeof setTimeout> | null = null;

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
      const anyImported = g.members.some((r) => {
        const sc = extractShortcode(r.emoji);
        return sc ? imported.has(sc) : false;
      });
      if (anyImported) {
        return { ...g, importable: false, importDomain: null };
      }
      return g;
    });
  };

  // Compute pHash only for custom emoji with unique shortcodes
  // (same-shortcode emoji are already grouped in Phase 1 of groupReactions)
  createEffect(() => {
    const currentMap = hashMap();

    // Count shortcode occurrences — multi-occurrence shortcodes don't need phash
    const scCounts = new Map<string, number>();
    for (const r of props.reactions) {
      if (!r.emoji_url) continue;
      const sc = extractShortcode(r.emoji);
      if (sc) scCounts.set(sc, (scCounts.get(sc) ?? 0) + 1);
    }

    const urlsToHash: string[] = [];
    for (const r of props.reactions) {
      if (!r.emoji_url || currentMap.has(r.emoji_url)) continue;
      if (inFlightUrls.has(r.emoji_url)) continue;
      const sc = extractShortcode(r.emoji);
      if (sc && (scCounts.get(sc) ?? 0) > 1) continue;
      urlsToHash.push(r.emoji_url);
    }

    if (urlsToHash.length === 0) return;
    for (const url of urlsToHash) inFlightUrls.add(url);

    Promise.all(
      urlsToHash.map(async (url) => {
        const hash = await computePhash(url);
        return hash ? { url, hash } : null;
      }),
    ).then((results) => {
      for (const url of urlsToHash) inFlightUrls.delete(url);
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

  // Reaction confirmation dialog for unsupported servers
  const [pendingReactionEmoji, setPendingReactionEmoji] = createSignal<string | null>(null);
  const [confirmDontShow, setConfirmDontShow] = createSignal(false);

  const doReaction = async (emoji: string) => {
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

  const toggleReaction = async (emoji: string) => {
    // Unreacting always works — no confirmation needed
    const existing = props.reactions.find((r) => r.emoji === emoji && r.me);
    if (existing) {
      return doReaction(emoji);
    }
    // New reaction: check if server ignores reactions and confirmation isn't suppressed
    if (ignoresReactions() && localStorage.getItem("hideReactionConfirm") !== "1") {
      setPendingReactionEmoji(emoji);
      setConfirmDontShow(false);
      return;
    }
    return doReaction(emoji);
  };

  const confirmReaction = () => {
    const emoji = pendingReactionEmoji();
    if (!emoji) return;
    if (confirmDontShow()) {
      localStorage.setItem("hideReactionConfirm", "1");
    }
    setPendingReactionEmoji(null);
    doReaction(emoji);
  };

  const cancelReaction = () => {
    setPendingReactionEmoji(null);
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
      activateTouchGuard();
      openModal(group);
    }, 500);
  };

  const cancelLongPress = () => {
    if (longPressTimer) {
      clearTimeout(longPressTimer);
      longPressTimer = null;
    }
  };

  const startReactionHover = (group: GroupedReaction) => {
    if (hoverHideTimer) { clearTimeout(hoverHideTimer); hoverHideTimer = null; }
    if (hoverGroup()?.displayEmoji === group.displayEmoji) return;
    if (hoverShowTimer) { clearTimeout(hoverShowTimer); hoverShowTimer = null; }
    hoverShowTimer = setTimeout(async () => {
      hoverShowTimer = null;
      let users: ReactionUser[] = [];
      try {
        const allUsers = await Promise.all(
          group.members.map((m) => getReactedBy(props.noteId, m.emoji)),
        );
        const seen = new Set<string>();
        for (const list of allUsers) {
          for (const u of list) {
            if (!seen.has(u.actor.id)) {
              seen.add(u.actor.id);
              users.push(u);
            }
          }
        }
      } catch {
        // ignore
      }
      setHoverUsers(users);
      setHoverLoading(false);
      setHoverGroup(group);
    }, 300);
  };

  const scheduleHideHover = () => {
    if (hoverShowTimer) { clearTimeout(hoverShowTimer); hoverShowTimer = null; }
    hoverHideTimer = setTimeout(() => {
      hoverHideTimer = null;
      setHoverGroup(null);
      setHoverUsers([]);
    }, 200);
  };

  const cancelHideHover = () => {
    if (hoverHideTimer) { clearTimeout(hoverHideTimer); hoverHideTimer = null; }
  };

  onCleanup(() => {
    cancelLongPress();
    if (hoverShowTimer) clearTimeout(hoverShowTimer);
    if (hoverHideTimer) clearTimeout(hoverHideTimer);
  });

  const ignoresReactions = () => props.serverSoftware === "mastodon";

  const badgeClass = (group: GroupedReaction) => {
    let cls = "reaction-badge";
    if (group.me) cls += " reaction-me";
    if (ignoresReactions()) cls += " reaction-unsupported";
    if (group.importable) {
      cls += canManageEmoji()
        ? " reaction-importable"
        : " reaction-remote-disabled";
    }
    return cls;
  };

  const checkEmojiOverflow = (badge: HTMLElement) => {
    const img = badge.querySelector("img.custom-emoji") as HTMLImageElement | null;
    if (!img) return;
    const check = () => {
      if (img.naturalWidth > img.clientWidth * 1.1) {
        badge.classList.add("emoji-overflow");
      } else {
        badge.classList.remove("emoji-overflow");
      }
    };
    if (img.complete) check();
    else img.addEventListener("load", check, { once: true });
  };

  return (
    <>
      <div class="reaction-bar">
        {grouped().map((g) => (
          <div
            class="action-popover-wrapper"
            onMouseEnter={() => { if (!isTouchMode()) startReactionHover(g); }}
            onMouseLeave={() => { if (!isTouchMode()) scheduleHideHover(); }}
          >
            <button
              class={badgeClass(g)}
              ref={checkEmojiOverflow}
              onClick={() => handleReaction(g)}
              onTouchStart={() => { if (isTouchMode()) startLongPress(g); }}
              onTouchEnd={(e) => { cancelLongPress(); if (didLongPress) { e.preventDefault(); } }}
              onContextMenu={(e) => e.preventDefault()}
            >
              <Emoji emoji={g.displayEmoji} url={g.displayUrl} /> {g.count}
            </button>
            <Show when={hoverGroup()?.displayEmoji === g.displayEmoji}>
              <div
                class="action-popover"
                onMouseEnter={cancelHideHover}
                onMouseLeave={scheduleHideHover}
              >
                <div class="action-popover-title">
                  <Emoji emoji={g.displayEmoji} url={g.displayUrl} />
                  <Show when={g.displayEmoji.startsWith(":")}>
                    <span>{g.displayEmoji.replace(/@[^:]+/, "")}</span>
                  </Show>
                </div>
                <Show when={hoverLoading()}>
                  <div style="padding: 12px; text-align: center; color: var(--text-secondary)">{t("common.loading")}</div>
                </Show>
                <Show when={!hoverLoading() && hoverUsers().length === 0}>
                  <div style="padding: 12px; text-align: center; color: var(--text-secondary)">—</div>
                </Show>
                <For each={hoverUsers()}>
                  {(ru) => {
                    const handle = ru.actor.domain
                      ? `@${ru.actor.username}@${ru.actor.domain}`
                      : `@${ru.actor.username}`;
                    return (
                      <button
                        class="reacted-by-item"
                        onClick={() => { setHoverGroup(null); navigate(`/${handle}`); }}
                      >
                        <img class="reacted-by-avatar" src={ru.actor.avatar_url || defaultAvatar()} alt="" />
                        <div class="reacted-by-names">
                          <span class="reacted-by-display">{ru.actor.display_name || ru.actor.username}</span>
                          <span class="reacted-by-handle">{handle}</span>
                        </div>
                      </button>
                    );
                  }}
                </For>
              </div>
            </Show>
          </div>
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
          <div class="modal-content reacted-by-modal" onClick={(e) => e.stopPropagation()}>
            <button class="reacted-by-close" onClick={closeModal}>✕</button>
            <div class="reacted-by-emoji-hero">
              <Emoji emoji={modalEmoji()!} url={modalUrl()} class="reacted-by-emoji-large" />
              {modalEmoji()!.startsWith(":") && (
                <span class="reacted-by-emoji-caption">{modalEmoji()!.replace(/@[^:]+/, "")}</span>
              )}
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

      {/* Reaction confirmation dialog for unsupported servers */}
      <Show when={pendingReactionEmoji()}>
        <div class="modal-overlay" onClick={cancelReaction}>
          <div class="modal-content reaction-confirm-modal" onClick={(e) => e.stopPropagation()}>
            <p class="reaction-confirm-message">{t("reactions.confirmUnsupported" as any)}</p>
            <label class="reaction-confirm-checkbox">
              <input
                type="checkbox"
                checked={confirmDontShow()}
                onChange={(e) => setConfirmDontShow(e.currentTarget.checked)}
              />
              {t("reactions.dontShowAgain" as any)}
            </label>
            <div class="reaction-confirm-buttons">
              <button class="reaction-confirm-cancel" onClick={cancelReaction}>
                {t("note.cancel")}
              </button>
              <button class="reaction-confirm-ok" onClick={confirmReaction}>
                {t("reactions.sendReaction" as any)}
              </button>
            </div>
          </div>
        </div>
      </Show>
    </>
  );
}
