import { Show } from "solid-js";
import type { Note } from "../../api/statuses";
import ReactionBar from "../reactions/ReactionBar";
import { currentUser } from "../../stores/auth";

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

export default function NoteCard(props: Props) {
  return (
    <div class="note-card">
      <div class="note-header">
        <strong class="note-display-name">
          {props.note.actor.display_name || props.note.actor.username}
        </strong>
        <span class="note-handle">{actorHandle(props.note.actor)}</span>
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
              {r.emoji} {r.count}
            </span>
          ))}
        </div>
      </Show>
    </div>
  );
}
