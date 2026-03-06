import { emojiToUrl } from "../utils/twemoji";

interface Props {
  emoji: string;
  class?: string;
}

export default function Emoji(props: Props) {
  return (
    <img
      class={`twemoji ${props.class ?? ""}`}
      src={emojiToUrl(props.emoji)}
      alt={props.emoji}
      draggable={false}
    />
  );
}
