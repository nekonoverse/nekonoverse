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
const RELOAD_COUNT_KEY = "nekonoverse_reload_count";
const RELOAD_TS_KEY = "nekonoverse_reload_ts";
const POLL_INTERVAL = 5 * 60 * 1000; // 5 minutes

// --- BroadcastChannel for multi-tab sync ---
const versionChannel =
  typeof BroadcastChannel !== "undefined"
    ? new BroadcastChannel("nekonoverse_version")
    : null;

versionChannel?.addEventListener("message", (e) => {
  if (e.data?.type === "version-changed") {
    location.reload();
  }
});

// --- Reload loop protection ---
function canReload(): boolean {
  const now = Date.now();
  const ts = Number(sessionStorage.getItem(RELOAD_TS_KEY) || "0");
  let count = Number(sessionStorage.getItem(RELOAD_COUNT_KEY) || "0");

  if (now - ts > 10_000) {
    // Reset counter after 10 seconds
    count = 0;
  }
  if (count >= 3) return false;

  sessionStorage.setItem(RELOAD_COUNT_KEY, String(count + 1));
  sessionStorage.setItem(RELOAD_TS_KEY, String(now));
  return true;
}

// --- Force reload: clear SW, caches, notify other tabs ---
async function forceReload() {
  if (!canReload()) return;
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
    forceReload();
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

    // Force reload when server version changes (deploy)
    const stored = localStorage.getItem(SERVER_VERSION_KEY);
    if (stored && stored !== info.version) {
      localStorage.setItem(SERVER_VERSION_KEY, info.version);
      await forceReload();
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
