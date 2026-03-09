import { For, Show } from "solid-js";
import { A } from "@solidjs/router";

interface BreadcrumbItem {
  label: string;
  href?: string;
}

export default function Breadcrumb(props: { items: BreadcrumbItem[] }) {
  return (
    <nav class="breadcrumb" aria-label="breadcrumb">
      <For each={props.items}>
        {(item, index) => (
          <>
            <Show when={index() > 0}>
              <span class="breadcrumb-separator">/</span>
            </Show>
            <Show when={item.href} fallback={
              <span class="breadcrumb-current">{item.label}</span>
            }>
              <A href={item.href!} class="breadcrumb-link">{item.label}</A>
            </Show>
          </>
        )}
      </For>
    </nav>
  );
}
