import { createSignal } from "solid-js";

const EMOJI_LIST = [
  "\u{1F44D}", "\u2764\uFE0F", "\u{1F602}", "\u{1F60D}", "\u{1F62E}",
  "\u{1F622}", "\u{1F621}", "\u{1F44F}", "\u{1F525}", "\u{1F389}",
  "\u{1F914}", "\u{1F60E}", "\u{1F631}", "\u{1F4AF}", "\u{1F440}",
  "\u{1F64F}", "\u{1F680}", "\u{1F31F}", "\u{1F43E}", "\u{1F431}",
];

interface Props {
  onSelect: (emoji: string) => void;
  onClose: () => void;
}

export default function EmojiPicker(props: Props) {
  return (
    <div class="emoji-picker">
      <div class="emoji-grid">
        {EMOJI_LIST.map((emoji) => (
          <button
            class="emoji-btn"
            onClick={() => {
              props.onSelect(emoji);
              props.onClose();
            }}
          >
            {emoji}
          </button>
        ))}
      </div>
    </div>
  );
}
