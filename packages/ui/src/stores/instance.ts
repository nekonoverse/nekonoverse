import { createSignal } from "solid-js";

interface MediaAttachmentsConfig {
  image_size_limit?: number;
  video_size_limit?: number;
  audio_size_limit?: number;
}

interface InstanceInfo {
  uri: string;
  title: string;
  description: string;
  version: string;
  registrations: boolean;
  registration_mode?: string;
  vapid_key?: string;
  tos_url?: string;
  privacy_policy_url?: string;
  turnstile_site_key?: string;
  thumbnail?: { url: string };
  stats?: {
    user_count: number;
    status_count: number;
    domain_count: number;
  };
  configuration?: {
    media_attachments?: MediaAttachmentsConfig;
  };
}

const CACHED_INSTANCE_KEY = "nekonoverse_cached_instance";

// localStorageから同期的にキャッシュを復元
function restoreCachedInstance(): InstanceInfo | null {
  try {
    const raw = localStorage.getItem(CACHED_INSTANCE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function cacheInstance(info: InstanceInfo | null) {
  try {
    if (info) {
      localStorage.setItem(CACHED_INSTANCE_KEY, JSON.stringify(info));
    } else {
      localStorage.removeItem(CACHED_INSTANCE_KEY);
    }
  } catch {
    // localStorage使用不可時は無視
  }
}

// キャッシュがあれば即座にinstanceLoading=falseで開始
const cachedInstance = restoreCachedInstance();
const [instance, setInstance] = createSignal<InstanceInfo | null>(cachedInstance);
const [instanceLoading, setInstanceLoading] = createSignal(!cachedInstance);
const [versionUpdateReady, setVersionUpdateReady] = createSignal(false);

export { instance, instanceLoading, versionUpdateReady };

export function registrationMode(): string {
  return (
    instance()?.registration_mode ??
    (instance()?.registrations ? "open" : "closed")
  );
}

export function inviteRequired(): boolean {
  return registrationMode() === "invite";
}

export function approvalRequired(): boolean {
  return registrationMode() === "approval";
}

export function defaultAvatar(): string {
  return instance()?.thumbnail?.url || "/default-avatar.svg";
}

export function turnstileSiteKey(): string | undefined {
  return instance()?.turnstile_site_key;
}

/** Get the upload size limit in bytes for the given MIME type. */
export function uploadSizeLimit(mimeType: string): number {
  const config = instance()?.configuration?.media_attachments;
  if (mimeType.startsWith("video/")) {
    return config?.video_size_limit ?? 40 * 1024 * 1024;
  }
  if (mimeType.startsWith("audio/")) {
    return config?.audio_size_limit ?? 10 * 1024 * 1024;
  }
  return config?.image_size_limit ?? 10 * 1024 * 1024;
}

function updateDynamicIcons(iconUrl: string) {
  // Favicon
  let link = document.querySelector(
    "link[rel='icon']",
  ) as HTMLLinkElement | null;
  if (!link) {
    link = document.createElement("link");
    link.rel = "icon";
    document.head.appendChild(link);
  }
  link.href = iconUrl;

  // Apple touch icon
  const apple = document.querySelector(
    "link[rel='apple-touch-icon']",
  ) as HTMLLinkElement | null;
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

// --- Clear all service workers and caches ---
export async function clearServiceWorkerAndCaches() {
  if ("serviceWorker" in navigator) {
    const regs = await navigator.serviceWorker.getRegistrations();
    await Promise.all(regs.map((r) => r.unregister()));
  }
  if ("caches" in window) {
    const keys = await caches.keys();
    await Promise.all(keys.map((k) => caches.delete(k)));
  }
}

// --- Apply update: clear SW, caches, notify other tabs, reload ---
export async function applyUpdate() {
  versionChannel?.postMessage({ type: "version-changed" });
  await clearServiceWorkerAndCaches();
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

// --- Fetch instance (バックグラウンドrevalidation) ---
async function fetchInstanceRaw(): Promise<InstanceInfo> {
  const resp = await fetch("/api/v1/instance", { cache: "no-store" });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

export async function fetchInstance() {
  // キャッシュ済みならloadingフラグを立てない(UIをブロックしない)
  if (!instance()) setInstanceLoading(true);
  try {
    const info = await fetchInstanceRaw();
    setInstance(info);
    cacheInstance(info);

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
    // キャッシュがなければnullに設定
    if (!instance()) setInstance(null);
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
