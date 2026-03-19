import { Show } from "solid-js";
import { emojiToUrl } from "@nekonoverse/ui/utils/twemoji";

interface Props {
  emoji: string;
  url?: string | null;
  class?: string;
}

export default function Emoji(props: Props) {
  const isCustom = () => props.emoji.startsWith(":") && props.emoji.endsWith(":");
  const shortcode = () => props.emoji.replace(/^:|:$/g, "").split("@")[0];

  return (
    <Show
      when={props.url}
      fallback={
        <Show
          when={isCustom()}
          fallback={
            <img
              class={`twemoji ${props.class ?? ""}`}
              src={emojiToUrl(props.emoji)}
              alt={props.emoji}
              draggable={false}
            />
          }
        >
          <span>{props.emoji}</span>
        </Show>
      }
    >
      <img
        class={`custom-emoji ${props.class ?? ""}`}
        src={props.url!}
        alt={`:${shortcode()}:`}
        title={`:${shortcode()}:`}
        draggable={false}
      />
    </Show>
  );
}
