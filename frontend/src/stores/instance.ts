import { createSignal } from "solid-js";
import { apiRequest } from "../api/client";

interface InstanceInfo {
  uri: string;
  title: string;
  description: string;
  version: string;
  registrations: boolean;
  thumbnail?: { url: string };
}

const [instance, setInstance] = createSignal<InstanceInfo | null>(null);
const [instanceLoading, setInstanceLoading] = createSignal(true);

export { instance, instanceLoading };

export function registrationOpen(): boolean {
  return instance()?.registrations ?? false;
}

export function instanceIcon(): string | undefined {
  return instance()?.thumbnail?.url;
}

function updateDynamicIcons(iconUrl: string) {
  // Favicon
  let link = document.querySelector("link[rel='icon']") as HTMLLinkElement | null;
  if (!link) {
    link = document.createElement("link");
    link.rel = "icon";
    document.head.appendChild(link);
  }
  link.href = iconUrl;

  // Apple touch icon
  const apple = document.querySelector("link[rel='apple-touch-icon']") as HTMLLinkElement | null;
  if (apple) apple.href = iconUrl;
}

export async function fetchInstance() {
  setInstanceLoading(true);
  try {
    const info = await apiRequest<InstanceInfo>("/api/v1/instance");
    setInstance(info);
    if (info.thumbnail?.url) {
      updateDynamicIcons(info.thumbnail.url);
    }
  } catch {
    setInstance(null);
  } finally {
    setInstanceLoading(false);
  }
}
