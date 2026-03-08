import { Show, For, createSignal, createEffect, onCleanup } from "solid-js";
import { useLocation } from "@solidjs/router";
import { currentUser, logout } from "../../stores/auth";
import { connect, disconnect, onNotification, unreadCount, resetUnread } from "../../stores/streaming";
import { useI18n } from "../../i18n";
import type { Dictionary } from "../../i18n/dictionaries/ja";
import { getNotifications, type Notification } from "../../api/notifications";
import Emoji from "../Emoji";

const PREVIEW_COUNT = 5;

function notifIcon(type: string) {
  switch (type) {
    case "follow": return "\u{1F464}";
    case "mention": return "\u{1F4AC}";
    case "reblog": return "\u{1F501}";
    case "favourite": return "\u2B50";
    case "reaction": return "\u2728";
    default: return "\u{1F514}";
  }
}

export default function Navbar() {
  const { t } = useI18n();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = createSignal(false);

  // Notification preview state
  const [notifOpen, setNotifOpen] = createSignal(false);
  const [notifItems, setNotifItems] = createSignal<Notification[]>([]);
  const [notifLoaded, setNotifLoaded] = createSignal(false);
  const [notifHasMore, setNotifHasMore] = createSignal(false);
  let notifTimer: ReturnType<typeof setTimeout> | undefined;

  // Manage global SSE connection based on auth state
  createEffect(() => {
    if (currentUser()) {
      connect();
    } else {
      disconnect();
    }
  });

  // Invalidate notification preview cache when new notifications arrive
  const unsub = onNotification(() => {
    setNotifLoaded(false);
  });

  onCleanup(() => {
    unsub();
    disconnect();
  });

  const isActive = (path: string) => location.pathname === path;

  // Close dropdown on outside click
  const handleDocClick = (e: MouseEvent) => {
    const target = e.target as HTMLElement;
    if (!target.closest(".navbar-user-menu")) {
      setMenuOpen(false);
    }
  };

  if (typeof document !== "undefined") {
    document.addEventListener("click", handleDocClick);
    onCleanup(() => document.removeEventListener("click", handleDocClick));
  }

  const handleLogout = async () => {
    setMenuOpen(false);
    await logout();
    window.location.href = "/";
  };

  const loadNotifPreview = async () => {
    if (notifLoaded()) return;
    try {
      const data = await getNotifications({ limit: PREVIEW_COUNT + 1 });
      setNotifHasMore(data.length > PREVIEW_COUNT);
      setNotifItems(data.slice(0, PREVIEW_COUNT));
      setNotifLoaded(true);
    } catch {}
  };

  const handleNotifEnter = () => {
    clearTimeout(notifTimer);
    loadNotifPreview();
    setNotifOpen(true);
  };

  const handleNotifLeave = () => {
    notifTimer = setTimeout(() => setNotifOpen(false), 200);
  };

  return (
    <nav class="navbar">
      <div class="navbar-inner">
        <div class="navbar-left">
          <a href="/" class="navbar-brand">{t("app.title")}</a>
          <a
            href="/"
            class={`navbar-icon${isActive("/") && !location.search.includes("tl=home") ? " active" : ""}`}
            title={t("timeline.public")}
          >
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10" />
              <path d="M2 12h20" />
              <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
            </svg>
          </a>
          <Show when={currentUser()}>
            <a
              href="/?tl=home"
              class={`navbar-icon${location.search.includes("tl=home") ? " active" : ""}`}
              title={t("timeline.home")}
            >
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
                <polyline points="9 22 9 12 15 12 15 22" />
              </svg>
            </a>
          </Show>
          <a
            href="/search"
            class={`navbar-icon${isActive("/search") ? " active" : ""}`}
            title={t("search.title")}
          >
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
          </a>
        </div>
        <div class="navbar-right">
          <Show
            when={currentUser()}
            fallback={
              <a href="/login" class="navbar-login-btn">
                {t("common.login")}
              </a>
            }
          >
            {(user) => (
              <>
                <div class="navbar-user-menu">
                  <img
                    src={user().avatar_url || "/default-avatar.svg"}
                    alt={user().username}
                    class="navbar-avatar"
                    onClick={() => setMenuOpen(!menuOpen())}
                  />
                  <Show when={menuOpen()}>
                    <div class="navbar-dropdown">
                      <a
                        href={`/@${user().username}`}
                        class="navbar-dropdown-item"
                        onClick={() => setMenuOpen(false)}
                      >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg>
                        {t("nav.profile")}
                      </a>
                      <a
                        href="/drive"
                        class="navbar-dropdown-item"
                        onClick={() => setMenuOpen(false)}
                      >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" /></svg>
                        {t("drive.title")}
                      </a>
                      <a
                        href="/bookmarks"
                        class="navbar-dropdown-item"
                        onClick={() => setMenuOpen(false)}
                      >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" /></svg>
                        {t("bookmark.title")}
                      </a>
                      <a
                        href="/settings"
                        class="navbar-dropdown-item"
                        onClick={() => setMenuOpen(false)}
                      >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
                        {t("settings.title")}
                      </a>
                      <button
                        class="navbar-dropdown-item navbar-dropdown-logout"
                        onClick={handleLogout}
                      >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" /></svg>
                        {t("settings.logout")}
                      </button>
                    </div>
                  </Show>
                </div>
                <div
                  class="navbar-notif-wrap"
                  onMouseEnter={handleNotifEnter}
                  onMouseLeave={handleNotifLeave}
                >
                  <a
                    href="/notifications"
                    class={`navbar-icon${isActive("/notifications") ? " active" : ""}`}
                    title={t("notifications.title")}
                    onClick={() => resetUnread()}
                  >
                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                      <path d="M13.73 21a2 2 0 0 1-3.46 0" />
                    </svg>
                    <Show when={unreadCount() > 0}>
                      <span class="navbar-notif-badge">
                        {unreadCount() > 99 ? "99+" : unreadCount()}
                      </span>
                    </Show>
                  </a>
                  <Show when={notifOpen()}>
                    <div
                      class="navbar-notif-dropdown"
                      onMouseEnter={handleNotifEnter}
                      onMouseLeave={handleNotifLeave}
                    >
                      <Show
                        when={notifItems().length > 0}
                        fallback={
                          <div class="navbar-notif-empty">
                            {t("notifications.empty")}
                          </div>
                        }
                      >
                        <For each={notifItems()}>
                          {(notif) => (
                            <a
                              href="/notifications"
                              class={`navbar-notif-item${notif.read ? "" : " unread"}`}
                            >
                              <span class="navbar-notif-icon">{notifIcon(notif.type)}</span>
                              <span class="navbar-notif-text">
                                <strong>
                                  {notif.account?.display_name || notif.account?.username || "?"}
                                </strong>{" "}
                                {t(`notifications.type.${notif.type}` as keyof Dictionary)}
                                <Show when={notif.type === "reaction" && notif.emoji}>
                                  {" "}<Emoji emoji={notif.emoji!} />
                                </Show>
                              </span>
                            </a>
                          )}
                        </For>
                      </Show>
                      <Show when={notifHasMore() || notifItems().length > 0}>
                        <a href="/notifications" class="navbar-notif-more">
                          {t("notifications.loadMore")}
                        </a>
                      </Show>
                    </div>
                  </Show>
                </div>
                <Show when={user().role === "admin" || user().role === "moderator"}>
                  <a
                    href="/admin"
                    class={`navbar-icon${isActive("/admin") ? " active" : ""}`}
                    title={t("admin.title")}
                  >
                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                    </svg>
                  </a>
                </Show>
              </>
            )}
          </Show>
        </div>
      </div>
    </nav>
  );
}
