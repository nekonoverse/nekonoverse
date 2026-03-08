import { createSignal } from "solid-js";
import { apiRequest } from "../api/client";

interface InstanceInfo {
  uri: string;
  title: string;
  description: string;
  version: string;
  registrations: boolean;
  registration_mode?: string;
  thumbnail?: { url: string };
}

const [instance, setInstance] = createSignal<InstanceInfo | null>(null);
const [instanceLoading, setInstanceLoading] = createSignal(true);

export { instance, instanceLoading };

export function registrationOpen(): boolean {
  return instance()?.registrations ?? false;
}

export function registrationMode(): string {
  return instance()?.registration_mode ?? (instance()?.registrations ? "open" : "closed");
}

export function inviteRequired(): boolean {
  return registrationMode() === "invite";
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

const VERSION_KEY = "nekonoverse_version";

export async function fetchInstance() {
  setInstanceLoading(true);
  try {
    const info = await apiRequest<InstanceInfo>("/api/v1/instance");
    setInstance(info);

    // Force reload when server version changes (deploy)
    const stored = localStorage.getItem(VERSION_KEY);
    if (stored && stored !== info.version) {
      localStorage.setItem(VERSION_KEY, info.version);
      if ("serviceWorker" in navigator) {
        const regs = await navigator.serviceWorker.getRegistrations();
        await Promise.all(regs.map((r) => r.unregister()));
      }
      if ("caches" in window) {
        const keys = await caches.keys();
        await Promise.all(keys.map((k) => caches.delete(k)));
      }
      location.reload();
      return;
    }
    localStorage.setItem(VERSION_KEY, info.version);

    if (info.thumbnail?.url) {
      updateDynamicIcons(info.thumbnail.url);
    }
  } catch {
    setInstance(null);
  } finally {
    setInstanceLoading(false);
  }
}
