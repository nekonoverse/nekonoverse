import { createSignal, createResource, createEffect, onCleanup, Show, For } from "solid-js";
import { getNotifications, dismissNotification, clearNotifications, markAllNotificationsAsRead, type Notification } from "@nekonoverse/ui/api/notifications";
import { getUserAnnouncements, dismissAnnouncement, type MastodonAnnouncement } from "@nekonoverse/ui/api/announcements";
import NoteCard from "../components/notes/NoteCard";
import NoteThreadModal from "../components/notes/NoteThreadModal";
import Emoji from "../components/Emoji";
import { emojify } from "@nekonoverse/ui/utils/emojify";
import { twemojify } from "@nekonoverse/ui/utils/twemojify";
import { formatTimestamp, useTimeTick } from "@nekonoverse/ui/utils/formatTime";
import { getNote } from "@nekonoverse/ui/api/statuses";
import { onNotification, onReaction, resetUnread, unreadMentions, unreadOther, unreadAnnouncements, resetUnreadMentions, resetUnreadOther, resetUnreadAnnouncements, onAnnouncement } from "@nekonoverse/ui/stores/streaming";
import { useI18n } from "@nekonoverse/ui/i18n";
import { currentUser, authLoading } from "@nekonoverse/ui/stores/auth";
import { defaultAvatar } from "@nekonoverse/ui/stores/instance";
import { isPushSupported, getPermissionState, subscribeToPush, unsubscribeFromPush, isSubscribedToPush } from "@nekonoverse/ui/utils/pushNotification";
import type { Dictionary } from "@nekonoverse/ui/i18n/dictionaries/ja";

type Tab = "mentions" | "other" | "announcements";

function profileUrl(account: Notification["account"]): string {
  if (!account) return "#";
  return account.domain
    ? `/@${account.username}@${account.domain}`
    : `/@${account.username}`;
}

export default function Notifications() {
  const { t } = useI18n();
  // 未読がある方のタブを初期表示（メンションに未読がなく、その他に未読がある場合のみ切り替え）
  const initialTab: Tab = unreadMentions() === 0 && unreadOther() > 0 ? "other" : "mentions";
  const [tab, setTab] = createSignal<Tab>(initialTab);
  const [allNotifs, setAllNotifs] = createSignal<Notification[]>([]);
  const [loadingMore, setLoadingMore] = createSignal(false);
  const [hasMore, setHasMore] = createSignal(true);
  const [pushSubscribed, setPushSubscribed] = createSignal(false);
  const [pushToggling, setPushToggling] = createSignal(false);
  const [threadNoteId, setThreadNoteId] = createSignal<string | null>(null);
  const [announcements, setAnnouncements] = createSignal<MastodonAnnouncement[]>([]);
  const [announcementsLoaded, setAnnouncementsLoaded] = createSignal(false);

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

  const filtered = () => {
    const t = tab();
    return allNotifs().filter((n) =>
      t === "mentions"
        ? n.type === "mention" || n.type === "reply"
        : n.type !== "mention" && n.type !== "reply"
    );
  };

  const load = async () => {
    const data = await getNotifications({ limit: 40 });
    // SSE で先に追加された通知を失わないようマージ
    setAllNotifs((prev) => {
      if (prev.length === 0) return data;
      const dataIds = new Set(data.map((n) => n.id));
      const extra = prev.filter((n) => !dataIds.has(n.id));
      return extra.length > 0 ? [...extra, ...data] : data;
    });
    setHasMore(data.length >= 40);

    // 現在のタブが空で他方にデータがあれば自動切替
    const currentTab = tab();
    const all = allNotifs();
    const hasMentions = all.some((n) => n.type === "mention" || n.type === "reply");
    const hasOther = all.some((n) => n.type !== "mention" && n.type !== "reply");
    if (currentTab === "mentions" && !hasMentions && hasOther) {
      setTab("other");
    } else if (currentTab === "other" && !hasOther && hasMentions) {
      setTab("mentions");
    }
    return data;
  };

  const [initialData] = createResource(
    () => (!authLoading() && currentUser() ? true : false),
    async () => {
      const data = await load();
      resetUnread();
      try {
        await markAllNotificationsAsRead();
        setAllNotifs((prev) => prev.map((n) => ({ ...n, read: true })));
      } catch { /* ignore */ }
      return data;
    },
  );

  const unsub = onNotification(async (data) => {
    const eventData = data as { id?: string };
    try {
      // DB commit の可視化を待つためリトライ付きで取得
      for (let attempt = 0; attempt < 3; attempt++) {
        const fresh = await getNotifications({ limit: 5 });
        const target = eventData.id
          ? fresh.find((n) => n.id === eventData.id)
          : fresh[0];
        if (target) {
          setAllNotifs((prev) => {
            if (prev.some((n) => n.id === target.id)) return prev;
            return [target, ...prev];
          });
          break;
        }
        await new Promise((r) => setTimeout(r, 300 * (attempt + 1)));
      }
    } catch { /* ignore */ }
    resetUnread();
  });

  const unsubReaction = onReaction(async (data) => {
    const { id } = data as { id: string };
    if (!id) return;
    if (allNotifs().some((n) => n.status?.id === id)) {
      await refreshNote(id);
    }
  });

  const unsubAnnouncement = onAnnouncement(async () => {
    try {
      const fresh = await getUserAnnouncements();
      setAnnouncements(fresh);
    } catch { /* ignore */ }
  });

  // Load announcements when tab is selected
  createEffect(async () => {
    if (tab() === "announcements" && !announcementsLoaded()) {
      try {
        const data = await getUserAnnouncements();
        setAnnouncements(data);
        setAnnouncementsLoaded(true);
        resetUnreadAnnouncements();
      } catch { /* ignore */ }
    }
  });

  const handleDismissAnnouncement = async (id: string) => {
    try {
      await dismissAnnouncement(id);
      setAnnouncements((prev) => prev.map((a) => (a.id === id ? { ...a, read: true } : a)));
    } catch {}
  };

  onCleanup(() => { unsub(); unsubReaction(); unsubAnnouncement(); });

  const loadMore = async () => {
    const current = allNotifs();
    if (current.length === 0 || loadingMore()) return;
    setLoadingMore(true);
    try {
      const older = await getNotifications({
        max_id: current[current.length - 1].id,
        limit: 40,
      });
      setAllNotifs([...current, ...older]);
      setHasMore(older.length >= 40);
    } catch {
    } finally {
      setLoadingMore(false);
    }
  };

  const handleClearAll = async () => {
    try {
      await clearNotifications();
      setAllNotifs([]);
    } catch {}
  };

  const handleDismiss = async (id: string) => {
    try {
      await dismissNotification(id);
      setAllNotifs((prev) => prev.map((n) => (n.id === id ? { ...n, read: true } : n)));
    } catch {}
  };

  const refreshNote = async (noteId: string) => {
    try {
      const updated = await getNote(noteId);
      setAllNotifs((prev) =>
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
      case "follow": return "\u{1F464}";
      case "follow_request": return "\u{1F464}";
      case "mention": return "\u{1F4AC}";
      case "reply": return "\u{1F4AC}";
      case "reblog": return "\u{1F501}";
      case "favourite": return "\u2B50";
      case "reaction": return "\u2728";
      default: return "\u{1F514}";
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
          <Show when={allNotifs().length > 0}>
            <button class="btn btn-small" onClick={handleClearAll}>
              {t("notifications.clearAll")}
            </button>
          </Show>
        </div>
      </div>

      <div class="notif-tabs">
        <button
          class={`notif-tab${tab() === "mentions" ? " active" : ""}`}
          onClick={() => { setTab("mentions"); resetUnreadMentions(); }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: -2px; margin-right: 4px">
            <circle cx="12" cy="12" r="4" />
            <path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-3.92 7.94" />
          </svg>
          {t("notifications.tabMentions" as keyof Dictionary)}
          <Show when={unreadMentions() > 0}>
            <span class="notif-tab-badge">{unreadMentions() > 99 ? "99+" : unreadMentions()}</span>
          </Show>
        </button>
        <button
          class={`notif-tab${tab() === "other" ? " active" : ""}`}
          onClick={() => { setTab("other"); resetUnreadOther(); }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: -2px; margin-right: 4px">
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
            <path d="M13.73 21a2 2 0 0 1-3.46 0" />
          </svg>
          {t("notifications.tabOther" as keyof Dictionary)}
          <Show when={unreadOther() > 0}>
            <span class="notif-tab-badge">{unreadOther() > 99 ? "99+" : unreadOther()}</span>
          </Show>
        </button>
        <button
          class={`notif-tab${tab() === "announcements" ? " active" : ""}`}
          onClick={() => { setTab("announcements"); resetUnreadAnnouncements(); }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: -2px; margin-right: 4px">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
          {t("announcements.title" as keyof Dictionary)}
          <Show when={unreadAnnouncements() > 0}>
            <span class="notif-tab-badge">{unreadAnnouncements() > 99 ? "99+" : unreadAnnouncements()}</span>
          </Show>
        </button>
      </div>

      <Show when={tab() === "announcements"}>
        <Show when={currentUser()} fallback={<p>{t("notifications.loginRequired")}</p>}>
          <Show
            when={announcements().length > 0}
            fallback={
              <p class="empty">
                {announcementsLoaded() ? t("announcements.empty" as keyof Dictionary) : t("common.loading")}
              </p>
            }
          >
            <div class="notifications-list">
              <For each={announcements()}>
                {(ann) => (
                  <div class={`notification-item announcement-item${ann.read ? "" : " unread"}`}>
                    <div class="notification-icon">{"\u{1F4E2}"}</div>
                    <div class="notification-body">
                      <div class="notification-meta">
                        <strong class="announcement-server-name">{t("announcements.fromServer" as keyof Dictionary)}</strong>
                        <Show when={!ann.read}>
                          <button
                            class="notification-dismiss"
                            onClick={() => handleDismissAnnouncement(ann.id)}
                            title={t("announcements.markAsRead" as keyof Dictionary)}
                          >
                            ✕
                          </button>
                        </Show>
                      </div>
                      <Show when={ann.title}>
                        <strong class="announcement-title">{ann.title}</strong>
                      </Show>
                      <span class="notification-time">
                        {(() => { useTimeTick(); return formatTimestamp(ann.published_at, t); })()}
                      </span>
                      <div class="announcement-content" innerHTML={ann.content} />
                    </div>
                  </div>
                )}
              </For>
            </div>
          </Show>
        </Show>
      </Show>

      <Show when={tab() !== "announcements"}>
        <Show when={initialData.state === "ready"} fallback={<p>{t("common.loading")}</p>}>
          <Show when={currentUser()} fallback={<p>{t("notifications.loginRequired")}</p>}>
            <Show
              when={filtered().length > 0}
              fallback={<p class="empty">{t("notifications.empty")}</p>}
            >
              <div class="notifications-list">
                <For each={filtered()}>
                  {(notif) => (
                    <div class={`notification-item${notif.read ? "" : " unread"}`}>
                      <div class="notification-icon">{notifIcon(notif.type)}</div>
                      <div class="notification-body">
                        <div class="notification-meta">
                          <Show when={notif.account}>
                            <a href={profileUrl(notif.account)} class="notification-actor">
                              <img
                                class="notification-avatar"
                                src={notif.account!.avatar || defaultAvatar()}
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
                            {t(`notifications.type.${notif.type}` as keyof Dictionary)}
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
                              onThreadOpen={(id) => setThreadNoteId(id)}
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
      </Show>

      {/* Thread modal */}
      <Show when={threadNoteId()}>
        <NoteThreadModal
          noteId={threadNoteId()!}
          onClose={() => setThreadNoteId(null)}
        />
      </Show>
    </div>
  );
}
