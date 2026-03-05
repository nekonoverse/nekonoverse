import { createSignal, createEffect, onMount, Show } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { currentUser, authLoading, fetchCurrentUser, logout } from "../stores/auth";
import { theme, setTheme, fontSize, setFontSize, type Theme, type FontSize } from "../stores/theme";
import { useI18n } from "../i18n";
import { updateDisplayName, updateAvatar, changePassword } from "../api/settings";
import PasskeyManager from "../components/PasskeyManager";

type Tab = "account" | "appearance" | "security";

export default function Settings() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = createSignal<Tab>("appearance");

  onMount(async () => {
    await fetchCurrentUser();
  });

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <div class="page-container">
      <h1>{t("settings.title")}</h1>

      <div class="settings-tabs">
        {([
          { key: "account" as Tab, label: t("settings.tabAccount") },
          { key: "appearance" as Tab, label: t("settings.tabAppearance") },
          { key: "security" as Tab, label: t("settings.tabSecurity") },
        ]).map((tab) => (
          <button
            class={`settings-tab${activeTab() === tab.key ? " settings-tab-active" : ""}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <Show when={activeTab() === "account"}>
        <AccountTab />
      </Show>
      <Show when={activeTab() === "appearance"}>
        <AppearanceTab />
      </Show>
      <Show when={activeTab() === "security"}>
        <SecurityTab onLogout={handleLogout} />
      </Show>
    </div>
  );
}

function AppearanceTab() {
  const { t } = useI18n();

  return (
    <>
      <div class="settings-section">
        <h3>{t("settings.theme")}</h3>
        <div class="theme-selector">
          {([
            { key: "dark" as Theme, label: t("settings.themeDark") },
            { key: "light" as Theme, label: t("settings.themeLight") },
            { key: "novel" as Theme, label: t("settings.themeNovel") },
          ]).map((item) => (
            <button
              class={`theme-btn${theme() === item.key ? " theme-active" : ""}`}
              onClick={() => setTheme(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div class="settings-section">
        <h3>{t("settings.fontSize")}</h3>
        <div class="theme-selector">
          {([
            { key: "small" as FontSize, label: t("settings.fontSmall") },
            { key: "medium" as FontSize, label: t("settings.fontMedium") },
            { key: "large" as FontSize, label: t("settings.fontLarge") },
            { key: "xlarge" as FontSize, label: t("settings.fontXLarge") },
            { key: "xxlarge" as FontSize, label: t("settings.fontXXLarge") },
          ]).map((item) => (
            <button
              class={`theme-btn${fontSize() === item.key ? " theme-active" : ""}`}
              onClick={() => setFontSize(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>
    </>
  );
}

function AuthGuard(props: { children: any }) {
  const { t } = useI18n();

  return (
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
        {props.children}
      </Show>
    </Show>
  );
}

function AccountTab() {
  const { t } = useI18n();
  const [displayName, setDisplayName] = createSignal("");
  const [saving, setSaving] = createSignal(false);
  const [saveMsg, setSaveMsg] = createSignal("");
  const [saveError, setSaveError] = createSignal("");

  const [avatarUploading, setAvatarUploading] = createSignal(false);
  const [avatarMsg, setAvatarMsg] = createSignal("");
  const [avatarError, setAvatarError] = createSignal("");

  const [currentPw, setCurrentPw] = createSignal("");
  const [newPw, setNewPw] = createSignal("");
  const [confirmPw, setConfirmPw] = createSignal("");
  const [changingPw, setChangingPw] = createSignal(false);
  const [pwMsg, setPwMsg] = createSignal("");
  const [pwError, setPwError] = createSignal("");

  createEffect(() => {
    const user = currentUser();
    if (user) setDisplayName(user.display_name ?? "");
  });

  const handleSaveDisplayName = async () => {
    setSaving(true);
    setSaveMsg("");
    setSaveError("");
    try {
      await updateDisplayName(displayName() || null);
      await fetchCurrentUser();
      setSaveMsg(t("settings.saved"));
    } catch (e: any) {
      setSaveError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const handleAvatarChange = async (e: Event) => {
    const input = e.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;

    setAvatarUploading(true);
    setAvatarMsg("");
    setAvatarError("");
    try {
      await updateAvatar(file);
      await fetchCurrentUser();
      setAvatarMsg(t("settings.saved"));
    } catch (err: any) {
      setAvatarError(err.message);
    } finally {
      setAvatarUploading(false);
      input.value = "";
    }
  };

  const handleChangePassword = async () => {
    setPwMsg("");
    setPwError("");
    if (newPw() !== confirmPw()) {
      setPwError(t("settings.passwordMismatch"));
      return;
    }
    setChangingPw(true);
    try {
      await changePassword(currentPw(), newPw());
      setPwMsg(t("settings.passwordChanged"));
      setCurrentPw("");
      setNewPw("");
      setConfirmPw("");
    } catch (e: any) {
      setPwError(e.message);
    } finally {
      setChangingPw(false);
    }
  };

  return (
    <AuthGuard>
      <div class="settings-section">
        <h3>{t("settings.account")}</h3>
        <p class="settings-username">@{currentUser()!.username}</p>

        <div class="avatar-upload" style="margin-top: 16px">
          <label>{t("settings.avatar")}</label>
          <div class="avatar-preview-row">
            <Show
              when={currentUser()!.avatar_url}
              fallback={<div class="avatar-placeholder" />}
            >
              <img class="avatar-preview" src={currentUser()!.avatar_url!} alt="avatar" />
            </Show>
            <label class="btn btn-small avatar-file-btn">
              {avatarUploading() ? t("common.loading") : t("settings.avatarUpload")}
              <input
                type="file"
                accept="image/jpeg,image/png,image/gif,image/webp"
                onChange={handleAvatarChange}
                disabled={avatarUploading()}
                style="display: none"
              />
            </label>
          </div>
          <Show when={avatarMsg()}><p class="settings-success">{avatarMsg()}</p></Show>
          <Show when={avatarError()}><p class="error">{avatarError()}</p></Show>
        </div>

        <div class="settings-form-group" style="margin-top: 16px">
          <label>{t("settings.displayName")}</label>
          <input
            type="text"
            value={displayName()}
            onInput={(e) => setDisplayName(e.currentTarget.value)}
            placeholder={t("settings.displayNamePlaceholder")}
          />
        </div>
        <Show when={saveMsg()}><p class="settings-success">{saveMsg()}</p></Show>
        <Show when={saveError()}><p class="error">{saveError()}</p></Show>
        <button
          class="btn btn-small"
          onClick={handleSaveDisplayName}
          disabled={saving()}
        >
          {t("settings.save")}
        </button>
      </div>

      <div class="settings-section">
        <h3>{t("settings.changePassword")}</h3>
        <Show when={pwMsg()}><p class="settings-success">{pwMsg()}</p></Show>
        <Show when={pwError()}><p class="error">{pwError()}</p></Show>
        <div class="settings-form-group">
          <label>{t("settings.currentPassword")}</label>
          <input
            type="password"
            value={currentPw()}
            onInput={(e) => setCurrentPw(e.currentTarget.value)}
          />
        </div>
        <div class="settings-form-group">
          <label>{t("settings.newPassword")}</label>
          <input
            type="password"
            value={newPw()}
            onInput={(e) => setNewPw(e.currentTarget.value)}
          />
        </div>
        <div class="settings-form-group">
          <label>{t("settings.confirmPassword")}</label>
          <input
            type="password"
            value={confirmPw()}
            onInput={(e) => setConfirmPw(e.currentTarget.value)}
          />
        </div>
        <button
          class="btn btn-small"
          onClick={handleChangePassword}
          disabled={changingPw() || !currentPw() || !newPw() || !confirmPw()}
        >
          {t("settings.changePassword")}
        </button>
      </div>
    </AuthGuard>
  );
}

function SecurityTab(props: { onLogout: () => void }) {
  const { t } = useI18n();

  return (
    <AuthGuard>
      <div class="settings-section">
        <PasskeyManager />
      </div>

      <div class="settings-section">
        <button class="btn-danger-full" onClick={props.onLogout}>
          {t("settings.logout")}
        </button>
      </div>
    </AuthGuard>
  );
}
