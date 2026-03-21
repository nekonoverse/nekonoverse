import { Show, For, createSignal, createEffect, onCleanup, batch } from "solid-js";
import type { Note, Poll, MediaAttachment } from "@nekonoverse/ui/api/statuses";
import {
  reblogNote,
  unreblogNote,
  deleteNote,
  bookmarkNote,
  unbookmarkNote,
  favouriteNote,
  unfavouriteNote,
  pinNote,
  unpinNote,
  votePoll,
  editNote,
  getRebloggedBy,
  getFavouritedBy,
} from "@nekonoverse/ui/api/statuses";
import type { ActionByUser } from "@nekonoverse/ui/api/statuses";
import { blockAccount, muteAccount } from "@nekonoverse/ui/api/accounts";
import LinkPreviewCard from "./LinkPreviewCard";
import ReactionBar from "../reactions/ReactionBar";
import { groupReactions } from "@nekonoverse/ui/utils/groupReactions";
import { getAllCachedPhashes } from "@nekonoverse/ui/utils/phashCache";
import Emoji from "../Emoji";
import ImageLightbox from "../ImageLightbox";
import { currentUser, canModerateContent } from "@nekonoverse/ui/stores/auth";
import { adminDeleteNote } from "@nekonoverse/ui/api/admin";
import UserHoverCard from "../UserHoverCard";
import { useI18n } from "@nekonoverse/ui/i18n";
import { focalPointToObjectPosition } from "@nekonoverse/ui/utils/focalPoint";
import { twemojify } from "@nekonoverse/ui/utils/twemojify";
import { emojify } from "@nekonoverse/ui/utils/emojify";
import { useNavigate } from "@solidjs/router";
import { mentionify } from "@nekonoverse/ui/utils/mentionify";
import { formatTimestamp, useTimeTick } from "@nekonoverse/ui/utils/formatTime";
import { timeFormat, nyaizeEnabled } from "@nekonoverse/ui/stores/theme";
import { sanitizeHtml } from "@nekonoverse/ui/utils/sanitize";
import { externalLinksNewTab } from "@nekonoverse/ui/utils/linkify";
import { renderMfm } from "@nekonoverse/ui/utils/mfm";
import { activateTouchGuard } from "../../utils/touchGuard";
import { nyaizeElement } from "@nekonoverse/ui/utils/nyaize";
import { defaultAvatar } from "@nekonoverse/ui/stores/instance";

interface Props {
  note: Note;
  onReactionUpdate?: () => void;
  onQuote?: (note: Note) => void;
  onDelete?: (noteId: string) => void;
  onReply?: (note: Note) => void;
  onThreadOpen?: (noteId: string) => void;
  inReplyToActor?: { username: string; domain: string | null } | null;
}

function actorHandle(actor: Note["actor"]): string {
  return actor.domain
    ? `@${actor.username}@${actor.domain}`
    : `@${actor.username}`;
}

function profileUrl(actor: Note["actor"]): string {
  return actor.domain
    ? `/@${actor.username}@${actor.domain}`
    : `/@${actor.username}`;
}

// CW展開状態・センシティブ解除状態をコンポーネント再マウント後も保持するためのモジュールレベル Set
const expandedCwNoteIds = new Set<string>();
const revealedSensitiveNoteIds = new Set<string>();

function QuoteEmbed(props: { note: Note }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [quoteRevealed, setQuoteRevealed] = createSignal(false);
  const handleClick = (e: MouseEvent) => {
    // Don't navigate if clicking a link inside the quote
    if ((e.target as HTMLElement).closest("a")) return;
    e.preventDefault();
    navigate(`/notes/${props.note.id}`);
  };
  return (
    <div class="note-quote-embed" onClick={handleClick}>
      <div class="note-quote-header">
        <img
          class="note-quote-avatar"
          src={props.note.actor.avatar_url || defaultAvatar()}
          alt=""
        />
        <a
          href={profileUrl(props.note.actor)}
          class="note-quote-name"
          onClick={(e) => e.stopPropagation()}
        >
          <strong
            ref={(el) => {
              el.textContent =
                props.note.actor.display_name || props.note.actor.username;
              emojify(el, props.note.actor.emojis || []);
              twemojify(el);
            }}
          />
          <span class="note-quote-handle">{actorHandle(props.note.actor)}</span>
        </a>
      </div>
      <div
        class="note-quote-content"
        ref={(el) => {
          if (props.note.source !== null && props.note.source !== undefined) {
            renderMfm(
              el,
              props.note.source,
              props.note.emojis,
              navigate,
              props.note.actor.domain,
            );
          } else {
            el.innerHTML = sanitizeHtml(props.note.content);
            mentionify(el, navigate);
            emojify(el, props.note.emojis);
            twemojify(el);
            externalLinksNewTab(el);
          }
        }}
      />
      <Show when={props.note.media_attachments?.length > 0}>
        <Show when={props.note.sensitive && !quoteRevealed()}>
          <div class="sensitive-overlay sensitive-overlay-small" onClick={(e) => { e.stopPropagation(); setQuoteRevealed(true); }}>
            <div class="sensitive-overlay-content">
              <span>{t("sensitive.label")}</span>
            </div>
          </div>
        </Show>
        <Show when={!props.note.sensitive || quoteRevealed()}>
          <div class={`note-quote-media note-quote-media-${Math.min(props.note.media_attachments.length, 4)}`}>
            <For each={props.note.media_attachments.slice(0, 4)}>
              {(media) => (
                <div class="note-quote-media-item">
                  <img
                    src={media.preview_url || media.url}
                    alt={media.description || ""}
                    loading="lazy"
                    style={{
                      "object-position": focalPointToObjectPosition(
                        media.meta?.focus,
                      ),
                    }}
                  />
                </div>
              )}
            </For>
          </div>
        </Show>
      </Show>
      <span class="note-quote-time">
        {(() => {
          useTimeTick();
          return formatTimestamp(props.note.published, t);
        })()}
      </span>
    </div>
  );
}

function PollDisplay(props: { poll: Poll; noteId: string }) {
  const { t } = useI18n();
  const [poll, setPoll] = createSignal(props.poll);
  const [selected, setSelected] = createSignal<number[]>([]);
  const [voting, setVoting] = createSignal(false);

  const hasVoted = () => poll().voted;
  const totalVotes = () => poll().votes_count || 1;

  const toggleChoice = (idx: number) => {
    if (hasVoted() || poll().expired) return;
    if (poll().multiple) {
      setSelected((prev) =>
        prev.includes(idx) ? prev.filter((i) => i !== idx) : [...prev, idx],
      );
    } else {
      setSelected([idx]);
    }
  };

  const handleVote = async () => {
    if (selected().length === 0 || voting()) return;
    setVoting(true);
    try {
      const updated = await votePoll(props.noteId, selected());
      setPoll(updated);
    } catch {}
    setVoting(false);
  };

  return (
    <div class="note-poll">
      <For each={poll().options}>
        {(opt, idx) => {
          const pct = () =>
            totalVotes() > 0
              ? Math.round((opt.votes_count / totalVotes()) * 100)
              : 0;
          const isOwn = () => poll().own_votes?.includes(idx());
          return (
            <div
              class={`poll-option${hasVoted() || poll().expired ? " poll-voted" : ""}${selected().includes(idx()) ? " poll-selected" : ""}${isOwn() ? " poll-own" : ""}`}
              onClick={() => toggleChoice(idx())}
            >
              <Show when={!hasVoted() && !poll().expired}>
                <span class="poll-check">
                  {poll().multiple
                    ? selected().includes(idx())
                      ? "\u2611"
                      : "\u2610"
                    : selected().includes(idx())
                      ? "\u25C9"
                      : "\u25CB"}
                </span>
              </Show>
              <span class="poll-option-text">{opt.title}</span>
              <Show when={hasVoted() || poll().expired}>
                <span class="poll-pct">{pct()}%</span>
                <div class="poll-bar" style={{ width: `${pct()}%` }} />
              </Show>
            </div>
          );
        }}
      </For>
      <div class="poll-footer">
        <Show when={!hasVoted() && !poll().expired}>
          <button
            class="btn btn-small"
            onClick={handleVote}
            disabled={voting() || selected().length === 0}
          >
            {t("poll.vote")}
          </button>
        </Show>
        <span class="poll-info">
          {poll().votes_count} {t("poll.votes")}
          <Show when={poll().expires_at}>
            {" · "}
            {poll().expired
              ? t("poll.expired")
              : t("poll.expiresAt") +
                " " +
                formatTimestamp(poll().expires_at!, t, false, true)}
          </Show>
        </span>
      </div>
    </div>
  );
}

export default function NoteCard(props: Props) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [moreOpen, setMoreOpen] = createSignal(false);
  const [nyaizeSuppressed, setNyaizeSuppressed] = createSignal(false);
  const [boosted, setBoosted] = createSignal(props.note.reblogged || (props.note.reblog?.reblogged ?? false));
  const [boostLoading, setBoostLoading] = createSignal(false);
  const [boostCount, setBoostCount] = createSignal(0);
  const [bookmarked, setBookmarked] = createSignal(false);
  const [favourited, setFavourited] = createSignal(false);
  const [favCount, setFavCount] = createSignal(0);
  const [pinned, setPinned] = createSignal(false);
  const [lightboxIndex, setLightboxIndex] = createSignal<number | null>(null);
  const cwNoteId = () => (props.note.reblog || props.note).id;
  const [cwExpanded, setCwExpandedRaw] = createSignal(expandedCwNoteIds.has(cwNoteId()));
  const setCwExpanded = (v: boolean) => {
    setCwExpandedRaw(v);
    if (v) expandedCwNoteIds.add(cwNoteId());
    else expandedCwNoteIds.delete(cwNoteId());
  };
  const [contentCollapsed, setContentCollapsed] = createSignal(true);
  const [contentOverflows, setContentOverflows] = createSignal(false);
  const [sensitiveRevealed, setSensitiveRevealedRaw] = createSignal(
    revealedSensitiveNoteIds.has(cwNoteId())
  );
  const setSensitiveRevealed = (v: boolean) => {
    setSensitiveRevealedRaw(v);
    if (v) revealedSensitiveNoteIds.add(cwNoteId());
    else revealedSensitiveNoteIds.delete(cwNoteId());
  };
  const [editing, setEditing] = createSignal(false);
  const [editContent, setEditContent] = createSignal("");
  const [editSaving, setEditSaving] = createSignal(false);
  const [noteContent, setNoteContent] = createSignal(props.note.content);
  const [noteSource, setNoteSource] = createSignal(props.note.source);
  const [noteEditedAt, setNoteEditedAt] = createSignal(props.note.edited_at);

  // Long-press modal for boost/fav "who did this"
  const [actionModalTitle, setActionModalTitle] = createSignal<string | null>(null);
  const [actionModalUsers, setActionModalUsers] = createSignal<ActionByUser[]>([]);
  const [actionModalLoading, setActionModalLoading] = createSignal(false);
  let actionLongPressTimer: ReturnType<typeof setTimeout> | null = null;
  let actionDidLongPress = false;

  // If this is a reblog, the displayed note is the inner one
  const isReblog = () => !!props.note.reblog;
  const displayNote = () => props.note.reblog || props.note;

  // リノートの場合、内側のノートからシグナルを初期化する
  const initBoostCount = () => displayNote().renotes_count;
  batch(() => {
    setNoteContent(displayNote().content);
    setNoteSource(displayNote().source);
    setNoteEditedAt(displayNote().edited_at);
    if (boostCount() === 0) setBoostCount(initBoostCount());
    setFavourited(displayNote().favourited || false);
    setFavCount(displayNote().favourites_count || 0);
    if (displayNote().pinned) setPinned(true);
  });

  const isOwnNote = () => {
    const user = currentUser();
    const note = displayNote();
    return user && user.username === note.actor.username && !note.actor.domain;
  };

  // Close more menu on outside click
  const handleDocClick = (e: MouseEvent) => {
    const target = e.target as HTMLElement;
    if (!target.closest(".note-more-menu")) {
      setMoreOpen(false);
    }
  };

  // M-19: ドロップダウンが開いている時だけリスナーを追加してパフォーマンス改善
  createEffect(() => {
    if (moreOpen()) {
      document.addEventListener("click", handleDocClick);
    } else {
      document.removeEventListener("click", handleDocClick);
    }
  });
  onCleanup(() => document.removeEventListener("click", handleDocClick));

  const handleBlock = async () => {
    setMoreOpen(false);
    if (!confirm(t("block.confirmBlock"))) return;
    try {
      await blockAccount(displayNote().actor.id);
    } catch {}
  };

  const handleMute = async () => {
    setMoreOpen(false);
    if (!confirm(t("block.confirmMute"))) return;
    try {
      await muteAccount(displayNote().actor.id);
    } catch {}
  };

  const handleDelete = async () => {
    setMoreOpen(false);
    const msg = isOwnNote() ? t("note.confirmDelete") : t("note.confirmModDelete" as any);
    if (!confirm(msg)) return;
    try {
      if (isOwnNote()) {
        await deleteNote(displayNote().id);
      } else {
        await adminDeleteNote(displayNote().id);
      }
      props.onDelete?.(displayNote().id);
    } catch {}
  };

  const handlePin = async () => {
    setMoreOpen(false);
    try {
      if (pinned()) {
        await unpinNote(displayNote().id);
        setPinned(false);
      } else {
        await pinNote(displayNote().id);
        setPinned(true);
      }
    } catch {}
  };

  const handleEdit = () => {
    batch(() => {
      setMoreOpen(false);
      const source = noteSource() ?? "";
      setEditContent(source);
      setEditing(true);
    });
  };

  const handleEditSave = async () => {
    if (editSaving()) return;
    setEditSaving(true);
    try {
      const updated = await editNote(displayNote().id, editContent());
      setNoteContent(updated.content);
      setNoteSource(updated.source);
      setNoteEditedAt(updated.edited_at);
      setEditing(false);
    } catch {}
    setEditSaving(false);
  };

  const handleEditCancel = () => {
    setEditing(false);
  };

  const handleBookmark = async () => {
    try {
      if (bookmarked()) {
        await unbookmarkNote(displayNote().id);
        setBookmarked(false);
      } else {
        await bookmarkNote(displayNote().id);
        setBookmarked(true);
      }
    } catch {}
  };

  const handleFavourite = async () => {
    if (actionDidLongPress) return;
    try {
      if (favourited()) {
        await unfavouriteNote(displayNote().id);
        setFavourited(false);
        setFavCount((c) => Math.max(0, c - 1));
      } else {
        await favouriteNote(displayNote().id);
        setFavourited(true);
        setFavCount((c) => c + 1);
      }
      props.onReactionUpdate?.();
    } catch {}
  };

  const handleBoost = async () => {
    if (actionDidLongPress) return;
    if (boostLoading()) return;
    setBoostLoading(true);
    try {
      if (boosted()) {
        await unreblogNote(displayNote().id);
        setBoosted(false);
        setBoostCount((c) => Math.max(0, c - 1));
      } else {
        await reblogNote(displayNote().id);
        setBoosted(true);
        setBoostCount((c) => c + 1);
      }
    } catch {}
    setBoostLoading(false);
  };

  const handleQuote = () => {
    props.onQuote?.(displayNote());
  };

  // Long press on boost/fav to show who did it
  const openActionModal = async (
    title: string,
    fetcher: () => Promise<ActionByUser[]>,
  ) => {
    setActionModalTitle(title);
    setActionModalLoading(true);
    setActionModalUsers([]);
    try {
      setActionModalUsers(await fetcher());
    } catch {
      setActionModalUsers([]);
    }
    setActionModalLoading(false);
  };

  const closeActionModal = () => {
    setActionModalTitle(null);
    setActionModalUsers([]);
    actionDidLongPress = false;
  };

  const startActionLongPress = (
    title: string,
    fetcher: () => Promise<ActionByUser[]>,
  ) => {
    actionDidLongPress = false;
    actionLongPressTimer = setTimeout(() => {
      actionDidLongPress = true;
      activateTouchGuard();
      openActionModal(title, fetcher);
    }, 500);
  };

  const cancelActionLongPress = () => {
    if (actionLongPressTimer) {
      clearTimeout(actionLongPressTimer);
      actionLongPressTimer = null;
    }
  };

  onCleanup(() => cancelActionLongPress());

  let replyLongPressTimer: ReturnType<typeof setTimeout> | null = null;
  let replyDidLongPress = false;

  const handleReply = () => {
    if (replyDidLongPress) return;
    if (props.onReply) {
      props.onReply(displayNote());
    } else {
      navigate(`/notes/${displayNote().id}`);
    }
  };

  const startReplyLongPress = () => {
    if (note().replies_count <= 0) return;
    replyDidLongPress = false;
    replyLongPressTimer = setTimeout(() => {
      replyDidLongPress = true;
      activateTouchGuard();
      navigate(`/notes/${displayNote().id}`);
    }, 500);
  };

  const cancelReplyLongPress = () => {
    if (replyLongPressTimer) {
      clearTimeout(replyLongPressTimer);
      replyLongPressTimer = null;
    }
  };

  onCleanup(() => cancelReplyLongPress());

  const note = displayNote;

  // Determine the reply-to actor display
  const replyToDisplay = (): { username: string; domain: string | null } | null => {
    if (props.inReplyToActor) return props.inReplyToActor;
    // Fallback: use mentions from API response (first mention = reply target)
    const n = note();
    if (n.in_reply_to_id && n.mentions?.length > 0) {
      const m = n.mentions[0];
      const parts = m.acct.split("@");
      return { username: m.username, domain: parts.length > 1 ? parts[1] : null };
    }
    return null;
  };

  return (
    <>
    <div class={`note-card${pinned() ? " note-pinned" : ""}`} data-note-id={note().id}>
      <Show when={pinned() && !isReblog()}>
        <div class="note-pin-indicator">
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M12 17v5" />
            <path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16h14v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76z" />
          </svg>
          {t("note.pinned")}
        </div>
      </Show>
      <Show when={isReblog()}>
        <div class="note-reblog-banner">
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <polyline points="17 1 21 5 17 9" />
            <path d="M3 11V9a4 4 0 0 1 4-4h14" />
            <polyline points="7 23 3 19 7 15" />
            <path d="M21 13v2a4 4 0 0 1-4 4H3" />
          </svg>
        </div>
        <div class="note-reblog-indicator">
          <a
            href={profileUrl(props.note.actor)}
            ref={(el) => {
              el.textContent =
                props.note.actor.display_name || props.note.actor.username;
              emojify(el, props.note.actor.emojis || []);
              twemojify(el);
            }}
          />{" "}
          {t("boost.boosted")}
        </div>
      </Show>
      <Show when={replyToDisplay()}>
        {(actor) => (
          <a
            class="note-reply-indicator"
            href={note().in_reply_to_id ? `/notes/${note().in_reply_to_id}` : undefined}
            onClick={(e) => {
              const parentId = note().in_reply_to_id;
              if (parentId && props.onThreadOpen) {
                e.preventDefault();
                props.onThreadOpen(parentId);
              }
            }}
          >
            <svg
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <polyline points="9 17 4 12 9 7" />
              <path d="M20 18v-2a4 4 0 0 0-4-4H4" />
            </svg>
            {t("reply.replyingTo")} @{actor().username}
            {actor().domain ? `@${actor().domain}` : ""}
          </a>
        )}
      </Show>
      <a href={profileUrl(note().actor)} class="note-avatar-link">
        <img
          class="note-avatar"
          src={note().actor.avatar_url || defaultAvatar()}
          alt=""
        />
      </a>
      <div class="note-body">
        <div class="note-header">
          <div class="note-header-text">
            <UserHoverCard actorId={note().actor.id}>
              <a
                href={profileUrl(note().actor)}
                class="note-display-name-link"
                onClick={(e) => e.preventDefault()}
              >
                <strong
                  class="note-display-name"
                  ref={(el) => {
                    el.textContent =
                      note().actor.display_name || note().actor.username;
                    emojify(el, note().actor.emojis || []);
                    twemojify(el);
                  }}
                />
              </a>
            </UserHoverCard>
          </div>
          <div class="note-header-right">
            <span
              class="note-visibility-badge"
              title={t(`visibility.${note().visibility}` as any)}
            >
              {note().visibility === "public" && (
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                >
                  <circle cx="12" cy="12" r="10" />
                  <line x1="2" y1="12" x2="22" y2="12" />
                  <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
                </svg>
              )}
              {note().visibility === "unlisted" && (
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                >
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                  <path d="M7 11V7a5 5 0 0 1 9.9-1" />
                </svg>
              )}
              {note().visibility === "private" && (
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                >
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                  <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                </svg>
              )}
              {note().visibility === "direct" && (
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                >
                  <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
                  <polyline points="22,6 12,13 2,6" />
                </svg>
              )}
            </span>
            <Show when={note().actor.is_cat && nyaizeEnabled()}>
              <button
                class={`note-cat-btn${nyaizeSuppressed() ? " note-cat-suppressed" : ""}`}
                onClick={(e) => {
                  e.stopPropagation();
                  setNyaizeSuppressed(!nyaizeSuppressed());
                }}
                title={nyaizeSuppressed() ? t("note.nyaizeOff") : t("note.nyaizeOn")}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  {/* ears */}
                  <path d="M3 11 L5 2 L10 8" />
                  <path d="M21 11 L19 2 L14 8" />
                  {/* face */}
                  <ellipse cx="12" cy="14" rx="9" ry="8" />
                  {nyaizeSuppressed() ? (
                    <>
                      <line x1="7" y1="11" x2="10" y2="14" />
                      <line x1="10" y1="11" x2="7" y2="14" />
                      <line x1="14" y1="11" x2="17" y2="14" />
                      <line x1="17" y1="11" x2="14" y2="14" />
                    </>
                  ) : (
                    <>
                      <circle cx="8.5" cy="12.5" r="1.2" fill="currentColor" stroke="none" />
                      <circle cx="15.5" cy="12.5" r="1.2" fill="currentColor" stroke="none" />
                      <path d="M12 15 L11 16.5 L13 16.5 Z" fill="currentColor" stroke="none" />
                      <path d="M9 17.5 Q12 20 15 17.5" />
                    </>
                  )}
                </svg>
              </button>
            </Show>
            <Show when={currentUser()}>
              <div class="note-more-menu">
                <button
                  class="note-more-btn"
                  onClick={(e) => {
                    e.stopPropagation();
                    setMoreOpen(!moreOpen());
                  }}
                >
                  ···
                </button>
                <Show when={moreOpen()}>
                  <div class="note-more-dropdown">
                    <Show when={isOwnNote()}>
                      <button class="note-more-item" onClick={handleEdit}>
                        {t("note.edit")}
                      </button>
                      <button class="note-more-item" onClick={handlePin}>
                        {pinned() ? t("note.unpin") : t("note.pin")}
                      </button>
                      <button
                        class="note-more-item note-more-danger"
                        onClick={handleDelete}
                      >
                        {t("note.delete")}
                      </button>
                    </Show>
                    <Show when={!isOwnNote()}>
                      <button class="note-more-item" onClick={handleMute}>
                        {t("block.mute")} {actorHandle(note().actor)}
                      </button>
                      <button
                        class="note-more-item note-more-danger"
                        onClick={handleBlock}
                      >
                        {t("block.block")} {actorHandle(note().actor)}
                      </button>
                      <Show when={canModerateContent()}>
                        <button
                          class="note-more-item note-more-danger"
                          onClick={handleDelete}
                        >
                          {t("note.modDelete" as any)}
                        </button>
                      </Show>
                    </Show>
                  </div>
                </Show>
              </div>
            </Show>
          </div>
        </div>
        <Show when={note().spoiler_text}>
          <div
            class="note-cw-text"
            ref={(el) => {
              el.textContent = note().spoiler_text!;
              emojify(el, note().emojis);
              twemojify(el);
            }}
          />
          <button
            class="note-cw-toggle"
            onClick={() => setCwExpanded(!cwExpanded())}
          >
            {cwExpanded() ? t("cw.hide") : t("cw.show")}
          </button>
        </Show>
        <Show when={!note().spoiler_text || cwExpanded()}>
          <Show
            when={editing()}
            fallback={(() => {
              const hasContent = () => {
                const src = noteSource();
                if (src !== null && src !== undefined && src !== "") return true;
                const content = noteContent();
                return content !== null && content !== undefined && content !== "";
              };
              let contentEl: HTMLDivElement | undefined;
              const renderContent = () => {
                if (!contentEl) return;
                const el = contentEl;
                const src = noteSource();
                if (src !== null && src !== undefined) {
                  renderMfm(el, src, note().emojis, navigate, note().actor.domain);
                } else {
                  el.innerHTML = sanitizeHtml(noteContent());
                  mentionify(el, navigate);
                  emojify(el, note().emojis);
                  twemojify(el);
                  externalLinksNewTab(el);
                }
                if (note().actor.is_cat && nyaizeEnabled() && !nyaizeSuppressed()) {
                  nyaizeElement(el);
                }
              };
              // Re-render when nyaize suppression toggles
              createEffect(() => {
                nyaizeSuppressed();
                renderContent();
              });
              return (
                <Show when={hasContent()}>
                  <div
                    class="note-content"
                    classList={{ "note-content-collapsed": contentCollapsed() && contentOverflows() }}
                    ref={(el) => {
                      contentEl = el;
                      renderContent();
                      requestAnimationFrame(() => {
                        if (el.scrollHeight > el.clientHeight + 2) {
                          setContentOverflows(true);
                        }
                      });
                    }}
                  />
                  <Show when={contentOverflows() && contentCollapsed()}>
                    <button
                      class="note-cw-toggle"
                      onClick={() => setContentCollapsed(false)}
                    >
                      {t("cw.show")}
                    </button>
                  </Show>
                </Show>
              );
            })()}
          >
            <div class="note-edit-form">
              <textarea
                class="note-edit-textarea"
                value={editContent()}
                onInput={(e) => setEditContent(e.currentTarget.value)}
                rows={4}
              />
              <div class="note-edit-actions">
                <button
                  class="btn btn-small note-edit-save-btn"
                  onClick={handleEditSave}
                  disabled={editSaving()}
                >
                  {editSaving() ? t("note.editing") : t("note.save")}
                </button>
                <button
                  class="btn btn-small note-edit-cancel-btn"
                  onClick={handleEditCancel}
                >
                  {t("note.cancel")}
                </button>
              </div>
            </div>
          </Show>
          <Show when={note().poll}>
            <PollDisplay poll={note().poll!} noteId={note().id} />
          </Show>
          <Show when={note().media_attachments?.length > 0}>
            <Show when={note().sensitive && !note().spoiler_text && !sensitiveRevealed()}>
              <div class="sensitive-overlay" onClick={() => setSensitiveRevealed(true)}>
                <div class="sensitive-overlay-content">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                    <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
                    <line x1="1" y1="1" x2="23" y2="23" />
                  </svg>
                  <span>{t("sensitive.label")}</span>
                  <span class="sensitive-overlay-action">{t("sensitive.show")}</span>
                </div>
              </div>
            </Show>
            <Show when={!note().sensitive || note().spoiler_text || sensitiveRevealed()}>
              <Show when={note().sensitive && !note().spoiler_text && sensitiveRevealed()}>
                <button class="sensitive-hide-btn" onClick={() => setSensitiveRevealed(false)}>
                  {t("sensitive.hide")}
                </button>
              </Show>
              <div
                class={`note-media note-media-${Math.min(note().media_attachments.length, 4)}`}
              >
                <For each={note().media_attachments.slice(0, 4)}>
                  {(media, i) => (
                    <button
                      class="note-media-item"
                      onClick={() => setLightboxIndex(i())}
                      type="button"
                    >
                      <img
                        src={media.preview_url || media.url}
                        alt={media.description || ""}
                        loading="lazy"
                        width={media.meta?.original?.width}
                        height={media.meta?.original?.height}
                        style={{
                          "object-position": focalPointToObjectPosition(
                            media.meta?.focus,
                          ),
                        }}
                        onLoad={(e) => {
                          const el = e.currentTarget;
                          const parent = el.parentElement;
                          if (!parent || !el.naturalWidth || !el.naturalHeight
                              || !el.clientWidth || !el.clientHeight) return;
                          const imgAR = el.naturalWidth / el.naturalHeight;
                          const boxAR = el.clientWidth / el.clientHeight;
                          if (imgAR > boxAR * 1.05) {
                            parent.setAttribute("data-crop", "horizontal");
                          } else if (imgAR < boxAR * 0.95) {
                            parent.setAttribute("data-crop", "vertical");
                          }
                        }}
                      />
                      <Show when={i() === 3 && note().media_attachments.length > 4}>
                        <div class="note-media-more">
                          +{note().media_attachments.length - 4}
                        </div>
                      </Show>
                    </button>
                  )}
                </For>
              </div>
              <Show when={lightboxIndex() !== null}>
                <ImageLightbox
                  media={note().media_attachments}
                  initialIndex={lightboxIndex()!}
                  onClose={() => setLightboxIndex(null)}
                />
              </Show>
            </Show>
          </Show>
          <Show when={note().quote}>
            <QuoteEmbed note={note().quote!} />
          </Show>
          <Show when={note().card && !note().media_attachments?.length}>
            <LinkPreviewCard card={note().card!} />
          </Show>
        </Show>
        <Show when={currentUser()}>
          <div class="note-actions">
            <button
              class="note-action-btn note-reply-btn"
              onClick={handleReply}
              onMouseDown={startReplyLongPress}
              onMouseUp={cancelReplyLongPress}
              onMouseLeave={cancelReplyLongPress}
              onTouchStart={startReplyLongPress}
              onTouchEnd={(e) => { cancelReplyLongPress(); if (replyDidLongPress) e.preventDefault(); }}
              title={t("reply.reply")}
            >
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
              <Show when={note().replies_count > 0}>
                <span class="note-action-count">{note().replies_count}</span>
              </Show>
            </button>
            <button
              class={`note-action-btn note-boost-btn${boosted() ? " boosted" : ""}${note().visibility === "private" || note().visibility === "direct" ? " disabled" : ""}`}
              onClick={handleBoost}
              onMouseDown={() => startActionLongPress(t("boost.boostedBy" as any), () => getRebloggedBy(displayNote().id))}
              onMouseUp={cancelActionLongPress}
              onMouseLeave={cancelActionLongPress}
              onTouchStart={() => startActionLongPress(t("boost.boostedBy" as any), () => getRebloggedBy(displayNote().id))}
              onTouchEnd={(e) => { cancelActionLongPress(); if (actionDidLongPress) e.preventDefault(); }}
              onContextMenu={(e) => e.preventDefault()}
              disabled={boostLoading() || note().visibility === "private" || note().visibility === "direct"}
              title={
                note().visibility === "private" || note().visibility === "direct"
                  ? t("boost.cannotRenote")
                  : t(boosted() ? "boost.unboost" : "boost.boost")
              }
            >
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <polyline points="17 1 21 5 17 9" />
                <path d="M3 11V9a4 4 0 0 1 4-4h14" />
                <polyline points="7 23 3 19 7 15" />
                <path d="M21 13v2a4 4 0 0 1-4 4H3" />
              </svg>
              <Show when={boostCount() > 0}>
                <span class="note-action-count">{boostCount()}</span>
              </Show>
            </button>
            <button
              class={`note-action-btn note-quote-btn${note().visibility === "private" || note().visibility === "direct" ? " disabled" : ""}`}
              onClick={handleQuote}
              disabled={note().visibility === "private" || note().visibility === "direct"}
              title={
                note().visibility === "private" || note().visibility === "direct"
                  ? t("boost.cannotRenote")
                  : t("boost.quote")
              }
            >
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                <path d="M8 9h8" />
                <path d="M8 13h4" />
              </svg>
            </button>
            <button
              class={`note-action-btn note-fav-btn${favourited() ? " favourited" : ""}`}
              onClick={handleFavourite}
              onMouseDown={() => startActionLongPress(t("favourite.favouritedBy" as any), () => getFavouritedBy(displayNote().id))}
              onMouseUp={cancelActionLongPress}
              onMouseLeave={cancelActionLongPress}
              onTouchStart={() => startActionLongPress(t("favourite.favouritedBy" as any), () => getFavouritedBy(displayNote().id))}
              onTouchEnd={(e) => { cancelActionLongPress(); if (actionDidLongPress) e.preventDefault(); }}
              onContextMenu={(e) => e.preventDefault()}
              title={t(favourited() ? "favourite.remove" : "favourite.add")}
            >
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill={favourited() ? "currentColor" : "none"}
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
              </svg>
              <Show when={favCount() > 0}>
                <span class="note-action-count">{favCount()}</span>
              </Show>
            </button>
            <button
              class={`note-action-btn note-bookmark-btn${bookmarked() ? " bookmarked" : ""}`}
              onClick={handleBookmark}
              title={t(bookmarked() ? "bookmark.remove" : "bookmark.add")}
            >
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill={bookmarked() ? "currentColor" : "none"}
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
              </svg>
            </button>
          </div>
          <ReactionBar
            noteId={note().id}
            reactions={note().reactions.filter((r) => r.emoji !== "\u2b50")}
            onUpdate={props.onReactionUpdate}
            serverSoftware={note().actor.server_software}
          />
        </Show>
        <Show when={!currentUser() && note().reactions.length > 0}>
          <div class="note-reactions">
            {groupReactions(note().reactions, getAllCachedPhashes()).map((g) => (
              <span class="reaction-badge reaction-badge-static">
                <Emoji emoji={g.displayEmoji} url={g.displayUrl} /> {g.count}
              </span>
            ))}
          </div>
        </Show>
        <div class="note-footer">
          <Show when={noteEditedAt()}>
            <span class="note-edited-label">{t("note.edited")}</span>
          </Show>
          <Show when={note().actor.domain && note().ap_id && /^https?:\/\//.test(note().ap_id!)}>
            <span class="note-via-label">
              <Show when={note().actor.server_software}>
                via <span class="note-via-software">{note().actor.server_software}</span>{" "}
              </Show>
              <a
                class="note-via-instance-link"
                href={note().ap_id}
                target="_blank"
                rel="noopener noreferrer"
                title={t("remote.viewOnRemote")}
              >
                (<span class="note-via-instance-name">{note().actor.server_name || note().actor.domain}</span>{" "}↗)
              </a>
            </span>
          </Show>
          <a
            href={`/notes/${note().id}`}
            class="note-time-link"
            onClick={(e) => {
              if (props.onThreadOpen) {
                e.preventDefault();
                props.onThreadOpen(note().id);
              }
            }}
          >
            <span class="note-time">
              <Show when={timeFormat() === "unixtime"}>
                <svg
                  class="note-time-icon"
                  width="12"
                  height="12"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                >
                  <circle cx="12" cy="12" r="10" />
                  <polyline points="12 6 12 12 16 14" />
                </svg>
              </Show>
              {(() => {
                useTimeTick();
                return formatTimestamp(note().published, t);
              })()}
            </span>
          </a>
        </div>
      </div>
    </div>

    {/* Boost/Favourite users modal (long press) */}
    <Show when={actionModalTitle()}>
      <div class="modal-overlay" onClick={closeActionModal}>
        <div class="modal-content reacted-by-modal" onClick={(e) => e.stopPropagation()}>
          <button class="reacted-by-close" onClick={closeActionModal}>✕</button>
          <div class="reacted-by-emoji-hero">
            <span style="font-size: 1.5rem; font-weight: 600">{actionModalTitle()}</span>
          </div>
          <div class="reacted-by-list">
            <Show when={actionModalLoading()}>
              <div style="padding: 24px; text-align: center; color: var(--text-secondary)">
                {t("common.loading")}
              </div>
            </Show>
            <Show when={!actionModalLoading() && actionModalUsers().length === 0}>
              <div style="padding: 24px; text-align: center; color: var(--text-secondary)">
                —
              </div>
            </Show>
            <For each={actionModalUsers()}>
              {(u) => {
                const handle = u.acct.includes("@") ? `@${u.acct}` : `@${u.acct}`;
                return (
                  <button
                    class="reacted-by-item"
                    onClick={() => { closeActionModal(); navigate(`/@${u.acct}`); }}
                  >
                    <img
                      class="reacted-by-avatar"
                      src={u.avatar || defaultAvatar()}
                      alt=""
                    />
                    <div class="reacted-by-names">
                      <span class="reacted-by-display">{u.display_name || u.username}</span>
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
