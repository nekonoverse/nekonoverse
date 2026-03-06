import { Show } from "solid-js";
import type { Note } from "../../api/statuses";
import ReactionBar from "../reactions/ReactionBar";
import Emoji from "../Emoji";
import { currentUser } from "../../stores/auth";
import UserHoverCard from "../UserHoverCard";

interface Props {
  note: Note;
  onReactionUpdate?: () => void;
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString();
}

function actorHandle(actor: Note["actor"]): string {
  return actor.domain ? `@${actor.username}@${actor.domain}` : `@${actor.username}`;
}

function profileUrl(actor: Note["actor"]): string {
  return actor.domain
    ? `/@${actor.username}@${actor.domain}`
    : `/@${actor.username}`;
}

export default function NoteCard(props: Props) {
  return (
    <div class="note-card">
      <a href={profileUrl(props.note.actor)} class="note-avatar-link">
        <img
          class="note-avatar"
          src={props.note.actor.avatar_url || "/default-avatar.svg"}
          alt=""
        />
      </a>
      <div class="note-body">
        <div class="note-header">
          <div class="note-header-text">
            <UserHoverCard actorId={props.note.actor.id}>
              <a href={profileUrl(props.note.actor)} class="note-display-name-link">
                <strong class="note-display-name">
                  {props.note.actor.display_name || props.note.actor.username}
                </strong>
              </a>
            </UserHoverCard>
            <span class="note-handle">{actorHandle(props.note.actor)}</span>
          </div>
          <span class="note-time">{formatTime(props.note.published)}</span>
        </div>
        <div class="note-content" innerHTML={props.note.content} />
        <Show when={currentUser()}>
          <ReactionBar
            noteId={props.note.id}
            reactions={props.note.reactions}
            onUpdate={props.onReactionUpdate}
          />
        </Show>
        <Show when={!currentUser() && props.note.reactions.length > 0}>
          <div class="note-reactions">
            {props.note.reactions.map((r) => (
              <span class="reaction-badge">
                <Emoji emoji={r.emoji} /> {r.count}
              </span>
            ))}
          </div>
        </Show>
      </div>
    </div>
  );
}
