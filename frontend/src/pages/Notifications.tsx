import { createSignal, createEffect, onMount, onCleanup, Show, For } from "solid-js";
import { getNotifications, dismissNotification, clearNotifications, type Notification } from "@nekonoverse/ui/api/notifications";
import NoteCard from "../components/notes/NoteCard";
import Emoji from "../components/Emoji";
import { emojify } from "@nekonoverse/ui/utils/emojify";
import { twemojify } from "@nekonoverse/ui/utils/twemojify";
import { formatTimestamp, useTimeTick } from "../utils/formatTime";
import { getNote } from "@nekonoverse/ui/api/statuses";
import { onNotification, onReaction, resetUnread } from "../stores/streaming";
import { useI18n } from "../i18n";
import { currentUser } from "../stores/auth";
import { defaultAvatar } from "../stores/instance";
import { isPushSupported, getPermissionState, subscribeToPush, unsubscribeFromPush, isSubscribedToPush } from "../utils/pushNotification";

function actorHandle(account: Notification["account"]): string {
  if (!account) return "";
  return account.domain ? `@${account.username}@${account.domain}` : `@${account.username}`;
}

function profileUrl(account: Notification["account"]): string {
  if (!account) return "#";
  return account.domain
    ? `/@${account.username}@${account.domain}`
    : `/@${account.username}`;
}

export default function Notifications() {
  const { t } = useI18n();
  const [notifications, setNotifications] = createSignal<Notification[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [loadingMore, setLoadingMore] = createSignal(false);
  const [hasMore, setHasMore] = createSignal(true);
  const [pushSubscribed, setPushSubscribed] = createSignal(false);
  const [pushToggling, setPushToggling] = createSignal(false);

  // プッシュ通知の状態を確認
  createEffect(async () => {
    if (currentUser() && isPushSupported()) {
      const subscribed = await isSubscribedToPush();
      setPushSubscribed(subscribed);
    }
  });

  const togglePush = async () => {
    setPushToggling(true);
    try {
      if (pushSubscribed()) {
        await unsubscribeFromPush();
        setPushSubscribed(false);
      } else {
        const result = await subscribeToPush();
        setPushSubscribed(result !== null);
      }
    } catch { /* ignore */ }
    setPushToggling(false);
  };

  const load = async () => {
    try {
      const data = await getNotifications({ limit: 20 });
      setNotifications(data);
      setHasMore(data.length >= 20);
    } catch {
    } finally {
      setLoading(false);
    }
  };

  onMount(() => {
    load();
    resetUnread();
  });

  // Subscribe to real-time notifications from global stream
  const unsub = onNotification(async () => {
    try {
      const fresh = await getNotifications({ limit: 1 });
      if (fresh.length > 0) {
        setNotifications((prev) => {
          if (prev.some((n) => n.id === fresh[0].id)) return prev;
          return [fresh[0], ...prev];
        });
      }
    } catch { /* ignore */ }
    resetUnread();
  });

  const unsubReaction = onReaction(async (data) => {
    const { id } = data as { id: string };
    if (!id) return;
    if (notifications().some((n) => n.status?.id === id)) {
      await refreshNote(id);
    }
  });

  onCleanup(() => { unsub(); unsubReaction(); });

  const loadMore = async () => {
    const current = notifications();
    if (current.length === 0 || loadingMore()) return;
    setLoadingMore(true);
    try {
      const older = await getNotifications({
        max_id: current[current.length - 1].id,
        limit: 20,
      });
      setNotifications([...current, ...older]);
      setHasMore(older.length >= 20);
    } catch {
    } finally {
      setLoadingMore(false);
    }
  };

  const handleClearAll = async () => {
    try {
      await clearNotifications();
      setNotifications([]);
    } catch {}
  };

  const handleDismiss = async (id: string) => {
    try {
      await dismissNotification(id);
      setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, read: true } : n)));
    } catch {}
  };

  const refreshNote = async (noteId: string) => {
    try {
      const updated = await getNote(noteId);
      setNotifications((prev) =>
        prev.map((n) => {
          if (n.status?.id === noteId) return { ...n, status: updated };
          if (n.status?.reblog?.id === noteId) {
            return { ...n, status: { ...n.status, reblog: updated } };
          }
          return n;
        })
      );
    } catch {}
  };

  const notifIcon = (type: string) => {
    switch (type) {
      case "follow": return "👤";
      case "mention": return "💬";
      case "reblog": return "🔁";
      case "favourite": return "⭐";
      case "reaction": return "✨";
      default: return "🔔";
    }
  };

  return (
    <div class="page-container">
      <div class="notifications-header">
        <h2>{t("notifications.title")}</h2>
        <div class="notifications-actions">
          <Show when={currentUser() && isPushSupported()}>
            <button
              class={`btn btn-small${pushSubscribed() ? " btn-active" : ""}`}
              onClick={togglePush}
              disabled={pushToggling() || getPermissionState() === "denied"}
              title={
                getPermissionState() === "denied"
                  ? t("push.denied")
                  : pushSubscribed()
                    ? t("push.disable")
                    : t("push.enable")
              }
            >
              {pushToggling()
                ? t("common.loading")
                : pushSubscribed()
                  ? t("push.enabled")
                  : t("push.disabled")}
            </button>
          </Show>
          <Show when={notifications().length > 0}>
            <button class="btn btn-small" onClick={handleClearAll}>
              {t("notifications.clearAll")}
            </button>
          </Show>
        </div>
      </div>

      <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
        <Show when={currentUser()} fallback={<p>{t("notifications.loginRequired")}</p>}>
          <Show
            when={notifications().length > 0}
            fallback={<p class="empty">{t("notifications.empty")}</p>}
          >
            <div class="notifications-list">
              <For each={notifications()}>
                {(notif) => (
                  <div class={`notification-item${notif.read ? "" : " unread"}`}>
                    <div class="notification-icon">{notifIcon(notif.type)}</div>
                    <div class="notification-body">
                      <div class="notification-meta">
                        <Show when={notif.account}>
                          <a href={profileUrl(notif.account)} class="notification-actor">
                            <img
                              class="notification-avatar"
                              src={notif.account!.avatar_url || defaultAvatar()}
                              alt=""
                            />
                            <strong ref={(el) => {
                              el.textContent = notif.account!.display_name || notif.account!.username;
                              emojify(el, notif.account!.emojis || []);
                              twemojify(el);
                            }} />
                          </a>
                        </Show>
                        <span class="notification-type-text">
                          {t(`notifications.type.${notif.type}` as keyof import("../i18n/dictionaries/ja").Dictionary)}
                        </span>
                        <Show when={notif.type === "reaction" && notif.emoji}>
                          <span class="notification-emoji">
                            <Emoji emoji={notif.emoji!} url={notif.emoji_url} />
                          </span>
                        </Show>
                        <Show when={!notif.read}>
                          <button
                            class="notification-dismiss"
                            onClick={() => handleDismiss(notif.id)}
                            title={t("notifications.dismiss")}
                          >
                            ✕
                          </button>
                        </Show>
                      </div>
                      <span class="notification-time">
                        {(() => { useTimeTick(); return formatTimestamp(notif.created_at, t); })()}
                      </span>
                      <Show when={notif.status}>
                        <div class="notification-note">
                          <NoteCard
                            note={notif.status!}
                            onReactionUpdate={() => refreshNote(notif.status!.id)}
                          />
                        </div>
                      </Show>
                    </div>
                  </div>
                )}
              </For>
            </div>
            <Show when={hasMore()}>
              <div class="load-more">
                <button
                  class="btn btn-small"
                  onClick={loadMore}
                  disabled={loadingMore()}
                >
                  {loadingMore() ? t("common.loading") : t("notifications.loadMore")}
                </button>
              </div>
            </Show>
          </Show>
        </Show>
      </Show>
    </div>
  );
}
