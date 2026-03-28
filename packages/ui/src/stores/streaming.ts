/**
 * グローバル SSE ストリーミングストア。
 * 全コンポーネントで共有する単一の EventSource 接続を管理する。
 * 認証状態に応じて connect()/disconnect() を呼び出す。
 * onUpdate/onNotification で購読し、返却された関数で解除する。
 */
import { createSignal } from "solid-js";

type Handler = (data: unknown) => void;

const updateHandlers = new Set<Handler>();
const notificationHandlers = new Set<Handler>();
const reactionHandlers = new Set<Handler>();
const emojiUpdateHandlers = new Set<Handler>();
const announcementHandlers = new Set<Handler>();

let es: EventSource | null = null;
let retryMs = 1000;
let retryTimer: ReturnType<typeof setTimeout> | null = null;
let intentionalClose = false;

const [connected, setConnected] = createSignal(false);
const [unreadCount, setUnreadCount] = createSignal(0);
const [unreadMentions, setUnreadMentions] = createSignal(0);
const [unreadOther, setUnreadOther] = createSignal(0);
const [pendingFollowRequests, setPendingFollowRequests] = createSignal(0);
const [unreadAnnouncements, setUnreadAnnouncements] = createSignal(0);

export { connected, unreadCount, setUnreadCount, unreadMentions, unreadOther, pendingFollowRequests, setPendingFollowRequests, unreadAnnouncements, setUnreadAnnouncements };

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
    } catch { /* 無視 */ }
  });

  es.addEventListener("notification", (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data);
      setUnreadCount((c: number) => c + 1);
      const type = (data as { type?: string }).type;
      if (type === "mention" || type === "reply") {
        setUnreadMentions((c: number) => c + 1);
      } else {
        setUnreadOther((c: number) => c + 1);
      }
      if (type === "follow" || type === "follow_request") {
        fetchFollowRequestCount();
      }
      notificationHandlers.forEach((h) => h(data));
    } catch { /* 無視 */ }
  });

  es.addEventListener("status.reaction", (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data);
      reactionHandlers.forEach((h) => h(data));
    } catch { /* 無視 */ }
  });

  es.addEventListener("emoji_update", () => {
    emojiUpdateHandlers.forEach((h) => h(null));
  });

  es.addEventListener("announcement", (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data);
      setUnreadAnnouncements((c: number) => c + 1);
      announcementHandlers.forEach((h) => h(data));
    } catch { /* 無視 */ }
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

/** APIから未読通知数を取得してシグナルを初期化する */
export async function fetchUnreadCount() {
  try {
    const resp = await fetch("/api/v1/notifications/unread_count", { credentials: "include" });
    if (resp.ok) {
      const data = await resp.json();
      setUnreadCount(data.total ?? 0);
      setUnreadMentions(data.mentions ?? 0);
      setUnreadOther(data.other ?? 0);
    }
  } catch { /* 無視 */ }
}

/** APIから未読お知らせ数を取得する */
export async function fetchAnnouncementsUnreadCount() {
  try {
    const resp = await fetch("/api/v1/announcements/unread_count", { credentials: "include" });
    if (resp.ok) {
      const data = await resp.json();
      setUnreadAnnouncements(data.count ?? 0);
    }
  } catch { /* 無視 */ }
}

/** 認証済みユーザー用のストリーミングを開始する */
export function connect() {
  disconnect();
  fetchUnreadCount();
  fetchAnnouncementsUnreadCount();
  doConnect("/api/v1/streaming/user");
}

/** 公開タイムライン用のストリーミングを開始する（未認証） */
export function connectPublic() {
  disconnect();
  doConnect("/api/v1/streaming/public");
}

/** ストリーミングを停止する */
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

/** タイムライン更新イベントを購読する。解除関数を返す。 */
export function onUpdate(handler: Handler): () => void {
  updateHandlers.add(handler);
  return () => updateHandlers.delete(handler);
}

/** 通知イベントを購読する。解除関数を返す。 */
export function onNotification(handler: Handler): () => void {
  notificationHandlers.add(handler);
  return () => notificationHandlers.delete(handler);
}

/** リアクション更新イベントを購読する。解除関数を返す。 */
export function onReaction(handler: Handler): () => void {
  reactionHandlers.add(handler);
  return () => reactionHandlers.delete(handler);
}

/** 絵文字更新イベントを購読する。解除関数を返す。 */
export function onEmojiUpdate(handler: Handler): () => void {
  emojiUpdateHandlers.add(handler);
  return () => emojiUpdateHandlers.delete(handler);
}

export function resetUnread() {
  setUnreadCount(0);
  setUnreadMentions(0);
  setUnreadOther(0);
}

export function resetUnreadAnnouncements() {
  setUnreadAnnouncements(0);
}

/** お知らせイベントを購読する。解除関数を返す。 */
export function onAnnouncement(handler: Handler): () => void {
  announcementHandlers.add(handler);
  return () => announcementHandlers.delete(handler);
}

export function resetUnreadMentions() {
  setUnreadMentions(0);
}

export function resetUnreadOther() {
  setUnreadOther(0);
}

/** APIから保留中のフォローリクエスト数を取得する */
export async function fetchFollowRequestCount() {
  try {
    const resp = await fetch("/api/v1/follow_requests", { credentials: "include" });
    if (resp.ok) {
      const data = await resp.json();
      setPendingFollowRequests(Array.isArray(data) ? data.length : 0);
    }
  } catch { /* 無視 */ }
}
