import { onMount, Show } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { currentUser, authLoading, fetchCurrentUser, logout } from "../stores/auth";
import { useI18n } from "../i18n";
import PasskeyManager from "../components/PasskeyManager";

export default function Settings() {
  const { t } = useI18n();
  const navigate = useNavigate();

  onMount(async () => {
    await fetchCurrentUser();
  });

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <div class="page-container">
      <div class="settings-header">
        <h1>{t("settings.title")}</h1>
        <a href="/" class="btn btn-secondary btn-small">{t("settings.backToHome")}</a>
      </div>
      <Show when={!authLoading()} fallback={<p>{t("common.loading")}</p>}>
        <Show
          when={currentUser()}
          fallback={
            <div class="auth-form">
              <p>{t("settings.loginRequired")}</p>
              <p class="alt-action">
                <a href="/login">{t("common.login")}</a>
              </p>
            </div>
          }
        >
          <div class="settings-section">
            <div class="settings-user-info">
              <h3>{t("settings.account")}</h3>
              <p class="settings-username">@{currentUser()!.username}</p>
            </div>
          </div>

          <div class="settings-section">
            <PasskeyManager />
          </div>

          <div class="settings-section">
            <button class="btn-danger-full" onClick={handleLogout}>
              {t("settings.logout")}
            </button>
          </div>
        </Show>
      </Show>
    </div>
  );
}
