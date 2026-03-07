import { emojiToUrl } from "../utils/twemoji";

interface Props {
  emoji: string;
  url?: string | null;
  class?: string;
}

export default function Emoji(props: Props) {
  if (props.url) {
    const shortcode = props.emoji.replace(/^:|:$/g, "").split("@")[0];
    return (
      <img
        class={`custom-emoji ${props.class ?? ""}`}
        src={props.url}
        alt={`:${shortcode}:`}
        title={`:${shortcode}:`}
        draggable={false}
      />
    );
  }

  if (props.emoji.startsWith(":") && props.emoji.endsWith(":")) {
    return <span>{props.emoji}</span>;
  }

  return (
    <img
      class={`twemoji ${props.class ?? ""}`}
      src={emojiToUrl(props.emoji)}
      alt={props.emoji}
      draggable={false}
    />
  );
}
