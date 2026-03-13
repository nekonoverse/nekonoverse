/// <reference lib="webworker" />
import { clientsClaim } from "workbox-core";
import { precacheAndRoute } from "workbox-precaching";
import { registerRoute } from "workbox-routing";
import { NetworkFirst } from "workbox-strategies";
import { ExpirationPlugin } from "workbox-expiration";

declare let self: ServiceWorkerGlobalScope;

// Auto-update: claim clients immediately
clientsClaim();

// Precache static assets (injected by vite-plugin-pwa)
precacheAndRoute(self.__WB_MANIFEST);

// Runtime cache for API requests (SSE and instance excluded)
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

// --- Web Push notification handler ---
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

  event.waitUntil(self.registration.showNotification(title, options));
});

// --- Notification click handler ---
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
