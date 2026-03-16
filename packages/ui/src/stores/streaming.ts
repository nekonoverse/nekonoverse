/**
 * Global SSE streaming store.
 * Manages a single EventSource connection shared across all components.
 * Call connect()/disconnect() based on auth state.
 * Subscribe with onUpdate/onNotification, unsubscribe with the returned function.
 */
import { createSignal } from "solid-js";

type Handler = (data: unknown) => void;

const updateHandlers = new Set<Handler>();
const notificationHandlers = new Set<Handler>();
const reactionHandlers = new Set<Handler>();

let es: EventSource | null = null;
let retryMs = 1000;
let retryTimer: ReturnType<typeof setTimeout> | null = null;
let intentionalClose = false;

const [connected, setConnected] = createSignal(false);
const [unreadCount, setUnreadCount] = createSignal(0);
const [unreadMentions, setUnreadMentions] = createSignal(0);
const [unreadOther, setUnreadOther] = createSignal(0);
const [pendingFollowRequests, setPendingFollowRequests] = createSignal(0);

export { connected, unreadCount, setUnreadCount, unreadMentions, unreadOther, pendingFollowRequests, setPendingFollowRequests };

function doConnect(path: string) {
  if (es) return;
  intentionalClose = false;

  es = new EventSource(path, { withCredentials: true });

  es.onopen = () => {
    retryMs = 1000;
    setConnected(true);
    fetchFollowRequestCount();
  };

  es.addEventListener("update", (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data);
      updateHandlers.forEach((h) => h(data));
    } catch { /* ignore */ }
  });

  es.addEventListener("notification", (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data);
      setUnreadCount((c) => c + 1);
      const type = (data as { type?: string }).type;
      if (type === "mention" || type === "reply") {
        setUnreadMentions((c) => c + 1);
      } else {
        setUnreadOther((c) => c + 1);
      }
      if (type === "follow") {
        fetchFollowRequestCount();
      }
      notificationHandlers.forEach((h) => h(data));
    } catch { /* ignore */ }
  });

  es.addEventListener("status.reaction", (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data);
      reactionHandlers.forEach((h) => h(data));
    } catch { /* ignore */ }
  });

  es.onerror = () => {
    setConnected(false);
    es?.close();
    es = null;
    if (!intentionalClose) {
      // ジッターを追加してサンダリングハード問題を防止
      const jitter = Math.random() * retryMs * 0.3;
      retryTimer = setTimeout(() => doConnect(path), retryMs + jitter);
      retryMs = Math.min(retryMs * 2, 30000);
    }
  };
}

/** Start streaming for authenticated user */
export function connect() {
  disconnect();
  doConnect("/api/v1/streaming/user");
}

/** Start streaming for public timeline (unauthenticated) */
export function connectPublic() {
  disconnect();
  doConnect("/api/v1/streaming/public");
}

/** Stop streaming */
export function disconnect() {
  intentionalClose = true;
  if (retryTimer) {
    clearTimeout(retryTimer);
    retryTimer = null;
  }
  if (es) {
    es.close();
    es = null;
  }
  setConnected(false);
}

/** Subscribe to timeline update events. Returns unsubscribe function. */
export function onUpdate(handler: Handler): () => void {
  updateHandlers.add(handler);
  return () => updateHandlers.delete(handler);
}

/** Subscribe to notification events. Returns unsubscribe function. */
export function onNotification(handler: Handler): () => void {
  notificationHandlers.add(handler);
  return () => notificationHandlers.delete(handler);
}

/** Subscribe to reaction update events. Returns unsubscribe function. */
export function onReaction(handler: Handler): () => void {
  reactionHandlers.add(handler);
  return () => reactionHandlers.delete(handler);
}

export function resetUnread() {
  setUnreadCount(0);
  setUnreadMentions(0);
  setUnreadOther(0);
}

export function resetUnreadMentions() {
  setUnreadMentions(0);
}

export function resetUnreadOther() {
  setUnreadOther(0);
}

/** Fetch pending follow request count from API */
export async function fetchFollowRequestCount() {
  try {
    const resp = await fetch("/api/v1/follow_requests", { credentials: "include" });
    if (resp.ok) {
      const data = await resp.json();
      setPendingFollowRequests(Array.isArray(data) ? data.length : 0);
    }
  } catch { /* ignore */ }
}
