import { Show, For, createSignal, onCleanup, batch } from "solid-js";
import type { Note, Poll, MediaAttachment } from "@nekonoverse/ui/api/statuses";
import {
  reblogNote,
  unreblogNote,
  deleteNote,
  bookmarkNote,
  unbookmarkNote,
  pinNote,
  unpinNote,
  votePoll,
  editNote,
} from "@nekonoverse/ui/api/statuses";
import { blockAccount, muteAccount } from "@nekonoverse/ui/api/accounts";
import ReactionBar from "../reactions/ReactionBar";
import Emoji from "../Emoji";
import ImageLightbox from "../ImageLightbox";
import { currentUser } from "@nekonoverse/ui/stores/auth";
import UserHoverCard from "../UserHoverCard";
import { useI18n } from "@nekonoverse/ui/i18n";
import { focalPointToObjectPosition } from "@nekonoverse/ui/utils/focalPoint";
import { twemojify } from "@nekonoverse/ui/utils/twemojify";
import { emojify } from "@nekonoverse/ui/utils/emojify";
import { useNavigate } from "@solidjs/router";
import { mentionify } from "@nekonoverse/ui/utils/mentionify";
import { formatTimestamp, useTimeTick } from "@nekonoverse/ui/utils/formatTime";
import { timeFormat } from "@nekonoverse/ui/stores/theme";
import { sanitizeHtml } from "@nekonoverse/ui/utils/sanitize";
import { externalLinksNewTab } from "@nekonoverse/ui/utils/linkify";
import { renderMfm } from "@nekonoverse/ui/utils/mfm";
import { defaultAvatar } from "@nekonoverse/ui/stores/instance";

interface Props {
  note: Note;
  onReactionUpdate?: () => void;
  onQuote?: (note: Note) => void;
  onDelete?: (noteId: string) => void;
  onReply?: (note: Note) => void;
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
          <div class="note-quote-media">
            <For each={props.note.media_attachments.slice(0, 2)}>
              {(media) => (
                <img
                  src={media.preview_url || media.url}
                  alt={media.description || ""}
                />
              )}
            </For>
          </div>
        </Show>
      </Show>
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
                formatTimestamp(poll().expires_at!, t)}
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
  const [boosted, setBoosted] = createSignal(props.note.reblogged || (props.note.reblog?.reblogged ?? false));
  const [boostLoading, setBoostLoading] = createSignal(false);
  const [boostCount, setBoostCount] = createSignal(0);
  const [bookmarked, setBookmarked] = createSignal(false);
  const [pinned, setPinned] = createSignal(false);
  const [lightboxIndex, setLightboxIndex] = createSignal<number | null>(null);
  const [cwExpanded, setCwExpanded] = createSignal(false);
  const [sensitiveRevealed, setSensitiveRevealed] = createSignal(false);
  const [editing, setEditing] = createSignal(false);
  const [editContent, setEditContent] = createSignal("");
  const [editSaving, setEditSaving] = createSignal(false);
  const [noteContent, setNoteContent] = createSignal(props.note.content);
  const [noteSource, setNoteSource] = createSignal(props.note.source);
  const [noteEditedAt, setNoteEditedAt] = createSignal(props.note.edited_at);

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

  if (typeof document !== "undefined") {
    document.addEventListener("click", handleDocClick);
    onCleanup(() => document.removeEventListener("click", handleDocClick));
  }

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
    if (!confirm(t("note.confirmDelete"))) return;
    try {
      await deleteNote(displayNote().id);
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

  const handleBoost = async () => {
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

  const handleReply = () => {
    if (props.onReply) {
      props.onReply(displayNote());
    } else {
      navigate(`/notes/${displayNote().id}`);
    }
  };

  const note = displayNote;

  // Determine the reply-to actor display
  const replyToDisplay = () => {
    if (props.inReplyToActor) return props.inReplyToActor;
    return null;
  };

  return (
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
          <div class="note-reply-indicator">
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
          </div>
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
              {note().visibility === "followers" && (
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
            fallback={
              <div
                class="note-content"
                ref={(el) => {
                  const src = noteSource();
                  if (src !== null && src !== undefined) {
                    renderMfm(
                      el,
                      src,
                      note().emojis,
                      navigate,
                      note().actor.domain,
                    );
                  } else {
                    el.innerHTML = sanitizeHtml(noteContent());
                    mentionify(el, navigate);
                    emojify(el, note().emojis);
                    twemojify(el);
                    externalLinksNewTab(el);
                  }
                }}
              />
            }
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
          <Show when={note().quote}>
            <QuoteEmbed note={note().quote!} />
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
                <For each={note().media_attachments}>
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
                      />
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
        </Show>
        <Show when={currentUser()}>
          <div class="note-actions">
            <button
              class="note-action-btn note-reply-btn"
              onClick={handleReply}
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
              class={`note-action-btn note-boost-btn${boosted() ? " boosted" : ""}${note().visibility === "followers" || note().visibility === "direct" ? " disabled" : ""}`}
              onClick={handleBoost}
              disabled={boostLoading() || note().visibility === "followers" || note().visibility === "direct"}
              title={
                note().visibility === "followers" || note().visibility === "direct"
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
              class={`note-action-btn note-quote-btn${note().visibility === "followers" || note().visibility === "direct" ? " disabled" : ""}`}
              onClick={handleQuote}
              disabled={note().visibility === "followers" || note().visibility === "direct"}
              title={
                note().visibility === "followers" || note().visibility === "direct"
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
            reactions={note().reactions}
            onUpdate={props.onReactionUpdate}
          />
        </Show>
        <Show when={!currentUser() && note().reactions.length > 0}>
          <div class="note-reactions">
            {note().reactions.map((r) => (
              <span class="reaction-badge reaction-badge-static">
                <Emoji emoji={r.emoji} url={r.emoji_url} /> {r.count}
              </span>
            ))}
          </div>
        </Show>
        <div class="note-footer">
          <Show when={noteEditedAt()}>
            <span class="note-edited-label">{t("note.edited")}</span>
          </Show>
          <Show when={note().actor.domain && note().ap_id && /^https?:\/\//.test(note().ap_id!)}>
            <a
              class="remote-view-link"
              href={note().ap_id}
              target="_blank"
              rel="noopener noreferrer"
              title={t("remote.viewOnRemote")}
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
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                <polyline points="15 3 21 3 21 9" />
                <line x1="10" y1="14" x2="21" y2="3" />
              </svg>
              {t("remote.viewOnRemote")}
            </a>
          </Show>
          <a href={`/notes/${note().id}`} class="note-time-link">
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
  );
}
