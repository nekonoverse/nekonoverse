import { createSignal, onMount, onCleanup, Show, For } from "solid-js";
import { getNotifications, dismissNotification, clearNotifications, type Notification } from "../api/notifications";
import NoteCard from "../components/notes/NoteCard";
import Emoji from "../components/Emoji";
import { getNote } from "../api/statuses";
import { createStream, type Stream } from "../api/streaming";
import { useI18n } from "../i18n";
import { currentUser } from "../stores/auth";

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

  let stream: Stream | null = null;

  onMount(() => {
    load();

    // Start SSE stream for real-time notification updates
    if (currentUser()) {
      stream = createStream("/api/v1/streaming/user");
      stream.on("notification", async () => {
        try {
          const fresh = await getNotifications({ limit: 1 });
          if (fresh.length > 0) {
            setNotifications((prev) => {
              if (prev.some((n) => n.id === fresh[0].id)) return prev;
              return [fresh[0], ...prev];
            });
          }
        } catch { /* ignore */ }
      });
    }
  });

  onCleanup(() => {
    stream?.close();
  });

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
        prev.map((n) =>
          n.status?.id === noteId ? { ...n, status: updated } : n
        )
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
        <Show when={notifications().length > 0}>
          <button class="btn btn-small" onClick={handleClearAll}>
            {t("notifications.clearAll")}
          </button>
        </Show>
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
                              src={notif.account!.avatar_url || "/default-avatar.svg"}
                              alt=""
                            />
                            <strong>{notif.account!.display_name || notif.account!.username}</strong>
                          </a>
                        </Show>
                        <span class="notification-type-text">
                          {t(`notifications.type.${notif.type}`)}
                        </span>
                        <Show when={notif.type === "reaction" && notif.emoji}>
                          <span class="notification-emoji">
                            <Emoji emoji={notif.emoji!} />
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
                        {new Date(notif.created_at).toLocaleString()}
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
