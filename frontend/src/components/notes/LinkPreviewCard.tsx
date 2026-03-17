import { Show } from "solid-js";
import type { PreviewCard } from "@nekonoverse/ui/api/statuses";

interface Props {
  card: PreviewCard;
}

export default function LinkPreviewCard(props: Props) {
  const domain = () => {
    try {
      return new URL(props.card.url).hostname;
    } catch {
      return props.card.provider_name || "";
    }
  };

  return (
    <a
      href={props.card.url}
      target="_blank"
      rel="noopener noreferrer"
      class="link-preview-card"
    >
      <Show when={props.card.image}>
        <div class="link-preview-card-image">
          <img
            src={props.card.image!}
            alt={props.card.title || ""}
            loading="lazy"
          />
        </div>
      </Show>
      <div class="link-preview-card-content">
        <Show when={props.card.provider_name || domain()}>
          <span class="link-preview-card-site">
            {props.card.provider_name || domain()}
          </span>
        </Show>
        <Show when={props.card.title}>
          <strong class="link-preview-card-title">{props.card.title}</strong>
        </Show>
        <Show when={props.card.description}>
          <p class="link-preview-card-description">{props.card.description}</p>
        </Show>
      </div>
    </a>
  );
}
