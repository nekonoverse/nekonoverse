import { createSignal, Show } from "solid-js";
import type { ReactionSummary } from "../../api/statuses";
import { reactToNote, unreactToNote } from "../../api/statuses";
import EmojiPicker from "./EmojiPicker";

interface Props {
  noteId: string;
  reactions: ReactionSummary[];
  onUpdate?: () => void;
}

export default function ReactionBar(props: Props) {
  const [showPicker, setShowPicker] = createSignal(false);

  const handleReaction = async (emoji: string) => {
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

  return (
    <div class="reaction-bar">
      {props.reactions.map((r) => (
        <button
          class={`reaction-badge ${r.me ? "reaction-me" : ""}`}
          onClick={() => handleReaction(r.emoji)}
        >
          {r.emoji} {r.count}
        </button>
      ))}
      <button class="reaction-add-btn" onClick={() => setShowPicker(!showPicker())}>
        +
      </button>
      <Show when={showPicker()}>
        <EmojiPicker
          onSelect={(emoji) => handleReaction(emoji)}
          onClose={() => setShowPicker(false)}
        />
      </Show>
    </div>
  );
}
