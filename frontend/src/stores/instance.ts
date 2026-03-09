import { createSignal } from "solid-js";

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
const [versionUpdateReady, setVersionUpdateReady] = createSignal(false);

export { instance, instanceLoading, versionUpdateReady };

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

export function defaultAvatar(): string {
  return instance()?.thumbnail?.url || "/default-avatar.svg";
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

// --- Version detection keys ---
const SERVER_VERSION_KEY = "nekonoverse_version";
const CLIENT_VERSION_KEY = "nekonoverse_client_version";
const POLL_INTERVAL = 5 * 60 * 1000; // 5 minutes

// --- BroadcastChannel for multi-tab sync ---
const versionChannel =
  typeof BroadcastChannel !== "undefined"
    ? new BroadcastChannel("nekonoverse_version")
    : null;

versionChannel?.addEventListener("message", (e) => {
  if (e.data?.type === "version-changed") {
    setVersionUpdateReady(true);
  }
});

// --- Apply update: clear SW, caches, notify other tabs, reload ---
export async function applyUpdate() {
  versionChannel?.postMessage({ type: "version-changed" });
  if ("serviceWorker" in navigator) {
    const regs = await navigator.serviceWorker.getRegistrations();
    await Promise.all(regs.map((r) => r.unregister()));
  }
  if ("caches" in window) {
    const keys = await caches.keys();
    await Promise.all(keys.map((k) => caches.delete(k)));
  }
  location.reload();
}

// --- Build-time client version check (call at module level) ---
export function checkClientVersion() {
  if (typeof __APP_VERSION__ === "undefined") return;
  const stored = localStorage.getItem(CLIENT_VERSION_KEY);
  if (stored && stored !== __APP_VERSION__) {
    localStorage.setItem(CLIENT_VERSION_KEY, __APP_VERSION__);
    setVersionUpdateReady(true);
    return;
  }
  localStorage.setItem(CLIENT_VERSION_KEY, __APP_VERSION__);
}

// --- Fetch instance with cache bypass ---
async function fetchInstanceRaw(): Promise<InstanceInfo> {
  const resp = await fetch("/api/v1/instance", { cache: "no-store" });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

export async function fetchInstance() {
  setInstanceLoading(true);
  try {
    const info = await fetchInstanceRaw();
    setInstance(info);

    // Notify when server version changes (deploy)
    const stored = localStorage.getItem(SERVER_VERSION_KEY);
    if (stored && stored !== info.version) {
      localStorage.setItem(SERVER_VERSION_KEY, info.version);
      setVersionUpdateReady(true);
      versionChannel?.postMessage({ type: "version-changed" });
      return;
    }
    localStorage.setItem(SERVER_VERSION_KEY, info.version);

    if (info.thumbnail?.url) {
      updateDynamicIcons(info.thumbnail.url);
    }
  } catch {
    setInstance(null);
  } finally {
    setInstanceLoading(false);
  }
}

// --- Periodic polling ---
export function startVersionPolling(): () => void {
  const id = setInterval(() => {
    fetchInstance();
  }, POLL_INTERVAL);
  return () => clearInterval(id);
}
