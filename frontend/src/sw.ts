/// <reference lib="webworker" />
import { clientsClaim } from "workbox-core";
import { precacheAndRoute } from "workbox-precaching";
import { registerRoute } from "workbox-routing";
import { NetworkFirst } from "workbox-strategies";
import { ExpirationPlugin } from "workbox-expiration";

declare let self: ServiceWorkerGlobalScope;

// 自動更新: 即座にクライアントを制御下に置く
clientsClaim();

// 静的アセットのプリキャッシュ（vite-plugin-pwaが注入）
precacheAndRoute(self.__WB_MANIFEST);

// APIリクエストのランタイムキャッシュ（SSEとinstanceは除外）
registerRoute(
  ({ url }) =>
    url.pathname.startsWith("/api/") &&
    !url.pathname.startsWith("/api/v1/streaming") &&
    !url.pathname.startsWith("/api/v1/instance"),
  new NetworkFirst({
    cacheName: "api-cache",
    plugins: [
      new ExpirationPlugin({
        maxEntries: 100,
        maxAgeSeconds: 60 * 5,
      }),
    ],
    networkTimeoutSeconds: 3,
  }),
);

// --- Web Push通知ハンドラ ---
self.addEventListener("push", (event) => {
  if (!event.data) return;

  let data: {
    title?: string;
    body?: string;
    notification_type?: string;
    notification_id?: string;
  };
  try {
    data = event.data.json();
  } catch {
    data = { title: "New notification", body: event.data.text() };
  }

  const title = data.title || "Nekonoverse";
  const options: NotificationOptions = {
    body: data.body || "",
    icon: "/pwa-192x192.svg",
    badge: "/pwa-192x192.svg",
    tag: data.notification_id || "default",
    data: {
      notification_type: data.notification_type,
      notification_id: data.notification_id,
    },
  };

  // アプリがフォーカス中はOS通知を抑制する（アプリ内表示はSSEが担当）
  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((clientList) => {
        const hasFocused = clientList.some(
          (c) => c.visibilityState === "visible" && c.url.includes(self.location.origin),
        );
        if (hasFocused) return;
        return self.registration.showNotification(title, options);
      }),
  );
});

// --- 通知クリックハンドラ ---
self.addEventListener("notificationclick", (event) => {
  event.notification.close();

  const notificationType = event.notification.data?.notification_type;

  // 通知ページに遷移
  let targetUrl = "/notifications";
  if (notificationType === "follow") {
    targetUrl = "/notifications";
  }

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      // 既に開いているウィンドウがあればフォーカス
      for (const client of clientList) {
        if (client.url.includes(self.location.origin) && "focus" in client) {
          client.focus();
          client.navigate(targetUrl);
          return;
        }
      }
      // なければ新しいウィンドウを開く
      return self.clients.openWindow(targetUrl);
    }),
  );
});
