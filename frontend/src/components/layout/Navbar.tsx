import { Show } from "solid-js";
import { useLocation } from "@solidjs/router";
import { currentUser } from "../../stores/auth";
import { useI18n, locales, type Locale } from "../../i18n";

export default function Navbar() {
  const { t, locale, setLocale } = useI18n();
  const location = useLocation();

  const isActive = (path: string) => location.pathname === path;

  const nextLocale = () => {
    const idx = locales.findIndex((l) => l.code === locale());
    return locales[(idx + 1) % locales.length];
  };

  return (
    <nav class="navbar">
      <div class="navbar-inner">
        <a href="/" class="navbar-brand">{t("app.title")}</a>
        <div class="navbar-links">
          <a href="/" class={`navbar-link${isActive("/") ? " active" : ""}`}>
            {t("timeline.public")}
          </a>
          <Show
            when={currentUser()}
            fallback={
              <a href="/login" class={`navbar-link${isActive("/login") ? " active" : ""}`}>
                {t("common.login")}
              </a>
            }
          >
            <a href="/settings" class={`navbar-link${isActive("/settings") ? " active" : ""}`}>
              {t("settings.title")}
            </a>
          </Show>
          <button
            class="navbar-lang"
            onClick={() => setLocale(nextLocale().code as Locale)}
            title={nextLocale().name}
          >
            {nextLocale().code.toUpperCase()}
          </button>
        </div>
      </div>
    </nav>
  );
}
