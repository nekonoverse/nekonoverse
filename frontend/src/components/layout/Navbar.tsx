import { Show, createSignal, createEffect, onCleanup } from "solid-js";
import { useLocation, useNavigate, useSearchParams } from "@solidjs/router";
import { currentUser, logout } from "@nekonoverse/ui/stores/auth";
import { connect, disconnect, unreadCount } from "@nekonoverse/ui/stores/streaming";
import { useI18n } from "@nekonoverse/ui/i18n";
import { defaultAvatar, instance } from "@nekonoverse/ui/stores/instance";
import { getNote, type Note } from "@nekonoverse/ui/api/statuses";
import SearchModal from "../SearchModal";
import ComposeModal from "../notes/ComposeModal";
import KeyboardShortcuts from "../KeyboardShortcuts";

export default function Navbar() {
  const { t } = useI18n();
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const isHomeTl = () => searchParams.tl === "home";
  const [menuOpen, setMenuOpen] = createSignal(false);
  const [searchOpen, setSearchOpen] = createSignal(false);
  const [composeOpen, setComposeOpen] = createSignal(false);
  const [composeQuote, setComposeQuote] = createSignal<Note | null>(null);
  const [composeReply, setComposeReply] = createSignal<Note | null>(null);
  const [tlDropdownOpen, setTlDropdownOpen] = createSignal(false);


  // Manage global SSE connection based on auth state
  createEffect(() => {
    if (currentUser()) {
      connect();
    } else {
      disconnect();
    }
  });

  // Close dropdowns on route change
  createEffect(() => {
    location.pathname; // track
    setMenuOpen(false);
    setTlDropdownOpen(false);
  });

  onCleanup(() => {
    disconnect();
  });

  const isActive = (path: string) => location.pathname === path;

  // Close dropdown on outside click
  const handleDocClick = (e: MouseEvent) => {
    const target = e.target as HTMLElement;
    if (!target.closest(".navbar-user-menu")) {
      setMenuOpen(false);
    }
    if (!target.closest(".navbar-tl-wrap")) {
      setTlDropdownOpen(false);
    }
  };

  if (typeof document !== "undefined") {
    document.addEventListener("click", handleDocClick);
    onCleanup(() => document.removeEventListener("click", handleDocClick));
  }

  const handleLogout = async () => {
    setMenuOpen(false);
    await logout();
    navigate("/");
  };


  return (
    <nav class="navbar">
      <div class="navbar-inner">
        <div class="navbar-left">
          <a href={isHomeTl() ? "/?tl=home" : "/"} class="navbar-brand">
            <Show when={instance()?.thumbnail?.url} fallback={<span class="navbar-brand-text">{instance()?.title || t("app.title")}</span>}>
              {(iconUrl) => (
                <>
                  <img src={iconUrl()} alt={instance()?.title || ""} class="navbar-brand-icon" />
                  <span class="navbar-brand-text">{instance()?.title || t("app.title")}</span>
                </>
              )}
            </Show>
          </a>
          <Show when={currentUser()}>
            <div class="navbar-tl-wrap">
              <button
                class={`navbar-icon${isHomeTl() || (isActive("/") && !isHomeTl()) ? " active" : ""}`}
                onClick={() => setTlDropdownOpen(!tlDropdownOpen())}
                title={isHomeTl() ? t("timeline.home") : t("timeline.public")}
              >
                <Show when={isHomeTl()} fallback={
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="12" cy="12" r="10" />
                    <line x1="2" y1="12" x2="22" y2="12" />
                    <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
                  </svg>
                }>
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
                    <polyline points="9 22 9 12 15 12 15 22" />
                  </svg>
                </Show>
                <svg class="navbar-tl-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              </button>
              <Show when={tlDropdownOpen()}>
                <div class="navbar-tl-dropdown">
                  <a
                    href="/?tl=home"
                    class={`navbar-tl-item${isHomeTl() ? " active" : ""}`}
                    onClick={() => setTlDropdownOpen(false)}
                  >
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
                      <polyline points="9 22 9 12 15 12 15 22" />
                    </svg>
                    {t("timeline.home")}
                  </a>
                  <a
                    href="/"
                    class={`navbar-tl-item${isActive("/") && !isHomeTl() ? " active" : ""}`}
                    onClick={() => setTlDropdownOpen(false)}
                  >
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <circle cx="12" cy="12" r="10" />
                      <line x1="2" y1="12" x2="22" y2="12" />
                      <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
                    </svg>
                    {t("timeline.public")}
                  </a>
                </div>
              </Show>
            </div>
            <a
              href="/notifications"
              class={`navbar-icon navbar-notif-link${isActive("/notifications") ? " active" : ""}`}
              title={t("notifications.title")}
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
          </Show>
          <button
            class="navbar-icon"
            title={t("search.title")}
            onClick={() => setSearchOpen(true)}
          >
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="10" cy="8" r="5" />
              <path d="M2 21v-2a5 5 0 0 1 5-5" />
              <circle cx="19" cy="19" r="3" />
              <line x1="22" y1="22" x2="21.1" y2="21.1" />
            </svg>
          </button>
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
                <button
                  class="navbar-compose-btn"
                  title={t("composer.post")}
                  onClick={() => { setComposeQuote(null); setComposeReply(null); setComposeOpen(true); }}
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z" />
                  </svg>
                </button>
                <div class="navbar-user-menu">
                  <img
                    src={user().avatar_url || defaultAvatar()}
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
                        href="/follow-requests"
                        class="navbar-dropdown-item"
                        onClick={() => setMenuOpen(false)}
                      >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="8.5" cy="7" r="4" /><line x1="20" y1="8" x2="20" y2="14" /><line x1="23" y1="11" x2="17" y2="11" /></svg>
                        {t("followRequest.title")}
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
      <Show when={searchOpen()}>
        <SearchModal onClose={() => setSearchOpen(false)} />
      </Show>
      <ComposeModal
        open={composeOpen()}
        onClose={() => { setComposeOpen(false); setComposeQuote(null); setComposeReply(null); }}
        onPost={(note) => {
          if (note.visibility !== "public" && location.pathname === "/" && !isHomeTl()) {
            navigate("/?tl=home");
          }
        }}
        quoteNote={composeQuote()}
        replyTo={composeReply()}
      />
      <Show when={currentUser()}>
        <KeyboardShortcuts
          disabled={composeOpen() || searchOpen()}
          onCompose={() => { setComposeQuote(null); setComposeReply(null); setComposeOpen(true); }}
          onQuote={async (noteId) => {
            try {
              const note = await getNote(noteId);
              setComposeReply(null);
              setComposeQuote(note);
              setComposeOpen(true);
            } catch {}
          }}
          onReply={async (noteId) => {
            try {
              const note = await getNote(noteId);
              setComposeQuote(null);
              setComposeReply(note);
              setComposeOpen(true);
            } catch {}
          }}
          onSearch={() => setSearchOpen(true)}
          onNavigate={(path) => navigate(path)}
        />
      </Show>
    </nav>
  );
}
