import { createSignal, onMount, Show, For } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { currentUser, authLoading, logout } from "../stores/auth";
import { theme, setTheme, fontSize, setFontSize, type Theme, type FontSize } from "../stores/theme";
import {
  defaultVisibility, setDefaultVisibility,
  rememberVisibility, setRememberVisibility,
} from "../stores/composer";
import VisibilitySelector from "../components/notes/VisibilitySelector";
import { useI18n, locales, type Locale } from "../i18n";
import { changePassword } from "../api/settings";
import { getBlockedAccounts, unblockAccount, getMutedAccounts, unmuteAccount, moveAccount, type Account } from "../api/accounts";
import PasskeyManager from "../components/PasskeyManager";

type Tab = "posting" | "appearance" | "security" | "blocks" | "mutes" | "migration";

export default function Settings() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = createSignal<Tab>("posting");

  // Auth is handled by App.tsx Layout

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <div class="page-container">
      <h1>{t("settings.title")}</h1>

      <div class="settings-tabs">
        {([
          { key: "posting" as Tab, label: t("settings.tabPosting") },
          { key: "appearance" as Tab, label: t("settings.tabAppearance") },
          { key: "security" as Tab, label: t("settings.tabSecurity") },
          { key: "blocks" as Tab, label: t("settings.tabBlocks") },
          { key: "mutes" as Tab, label: t("settings.tabMutes") },
          { key: "migration" as Tab, label: t("settings.tabMigration") },
        ]).map((tab) => (
          <button
            class={`settings-tab${activeTab() === tab.key ? " settings-tab-active" : ""}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <Show when={activeTab() === "posting"}>
        <PostingTab />
      </Show>
      <Show when={activeTab() === "appearance"}>
        <AppearanceTab />
      </Show>
      <Show when={activeTab() === "security"}>
        <SecurityTab onLogout={handleLogout} />
      </Show>
      <Show when={activeTab() === "blocks"}>
        <BlocksTab />
      </Show>
      <Show when={activeTab() === "mutes"}>
        <MutesTab />
      </Show>
      <Show when={activeTab() === "migration"}>
        <MigrationTab />
      </Show>
    </div>
  );
}

function AppearanceTab() {
  const { t, locale, setLocale } = useI18n();

  return (
    <>
      <div class="settings-section">
        <h3>{t("settings.language")}</h3>
        <div class="theme-selector">
          {locales.map((item) => (
            <button
              class={`theme-btn${locale() === item.code ? " theme-active" : ""}`}
              onClick={() => setLocale(item.code as Locale)}
            >
              {item.name}
            </button>
          ))}
        </div>
      </div>

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
            { key: "small" as FontSize, label: t("settings.fontSmall"), size: "14px" },
            { key: "medium" as FontSize, label: t("settings.fontMedium"), size: "16px" },
            { key: "large" as FontSize, label: t("settings.fontLarge"), size: "20px" },
            { key: "xlarge" as FontSize, label: t("settings.fontXLarge"), size: "24px" },
            { key: "xxlarge" as FontSize, label: t("settings.fontXXLarge"), size: "28px" },
          ]).map((item) => (
            <button
              class={`theme-btn${fontSize() === item.key ? " theme-active" : ""}`}
              style={{ "font-size": item.size }}
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

function PostingTab() {
  const { t } = useI18n();

  return (
    <div class="settings-section">
      <h3>{t("settings.defaultVisibility")}</h3>
      <VisibilitySelector
        value={defaultVisibility()}
        onChange={(v) => setDefaultVisibility(v)}
      />
      <label class="toggle-label">
        <input
          type="checkbox"
          checked={rememberVisibility()}
          onChange={(e) => setRememberVisibility(e.currentTarget.checked)}
        />
        {t("settings.rememberVisibility")}
      </label>
    </div>
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

function SecurityTab(props: { onLogout: () => void }) {
  const { t } = useI18n();
  const [currentPw, setCurrentPw] = createSignal("");
  const [newPw, setNewPw] = createSignal("");
  const [confirmPw, setConfirmPw] = createSignal("");
  const [changingPw, setChangingPw] = createSignal(false);
  const [pwMsg, setPwMsg] = createSignal("");
  const [pwError, setPwError] = createSignal("");

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

function BlocksTab() {
  const { t } = useI18n();
  const [accounts, setAccounts] = createSignal<Account[]>([]);
  const [loading, setLoading] = createSignal(true);

  onMount(async () => {
    try {
      setAccounts(await getBlockedAccounts());
    } catch {}
    setLoading(false);
  });

  const handleUnblock = async (id: string) => {
    try {
      await unblockAccount(id);
      setAccounts((prev) => prev.filter((a) => a.id !== id));
    } catch {}
  };

  return (
    <AuthGuard>
      <div class="settings-section">
        <h3>{t("block.blockedUsers")}</h3>
        <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
          <Show when={accounts().length > 0} fallback={<p class="empty">{t("block.noBlocked")}</p>}>
            <div class="blockmute-list">
              <For each={accounts()}>
                {(acc) => (
                  <div class="blockmute-item">
                    <a href={`/@${acc.acct}`} class="blockmute-user">
                      <img class="blockmute-avatar" src={acc.avatar || "/default-avatar.svg"} alt="" />
                      <div>
                        <strong>{acc.display_name || acc.username}</strong>
                        <span class="blockmute-handle">@{acc.acct}</span>
                      </div>
                    </a>
                    <button class="btn btn-small" onClick={() => handleUnblock(acc.id)}>
                      {t("block.unblock")}
                    </button>
                  </div>
                )}
              </For>
            </div>
          </Show>
        </Show>
      </div>
    </AuthGuard>
  );
}

function MutesTab() {
  const { t } = useI18n();
  const [accounts, setAccounts] = createSignal<Account[]>([]);
  const [loading, setLoading] = createSignal(true);

  onMount(async () => {
    try {
      setAccounts(await getMutedAccounts());
    } catch {}
    setLoading(false);
  });

  const handleUnmute = async (id: string) => {
    try {
      await unmuteAccount(id);
      setAccounts((prev) => prev.filter((a) => a.id !== id));
    } catch {}
  };

  return (
    <AuthGuard>
      <div class="settings-section">
        <h3>{t("block.mutedUsers")}</h3>

        <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
          <Show when={accounts().length > 0} fallback={<p class="empty">{t("block.noMuted")}</p>}>
            <div class="blockmute-list">
              <For each={accounts()}>
                {(acc) => (
                  <div class="blockmute-item">
                    <a href={`/@${acc.acct}`} class="blockmute-user">
                      <img class="blockmute-avatar" src={acc.avatar || "/default-avatar.svg"} alt="" />
                      <div>
                        <strong>{acc.display_name || acc.username}</strong>
                        <span class="blockmute-handle">@{acc.acct}</span>
                      </div>
                    </a>
                    <button class="btn btn-small" onClick={() => handleUnmute(acc.id)}>
                      {t("block.unmute")}
                    </button>
                  </div>
                )}
              </For>
            </div>
          </Show>
        </Show>
      </div>
    </AuthGuard>
  );
}

function MigrationTab() {
  const { t } = useI18n();
  const [targetApId, setTargetApId] = createSignal("");
  const [migrating, setMigrating] = createSignal(false);
  const [msg, setMsg] = createSignal("");
  const [error, setError] = createSignal("");

  const handleMove = async () => {
    if (!targetApId().trim()) return;
    if (!confirm(t("migration.confirm"))) return;
    setMigrating(true);
    setMsg("");
    setError("");
    try {
      await moveAccount(targetApId());
      setMsg(t("migration.success"));
      setTargetApId("");
    } catch (e: any) {
      setError(e.message || t("migration.failed"));
    } finally {
      setMigrating(false);
    }
  };

  return (
    <AuthGuard>
      <div class="settings-section">
        <h3>{t("migration.title")}</h3>
        <p class="settings-desc">{t("migration.description")}</p>
        <Show when={msg()}><p class="settings-success">{msg()}</p></Show>
        <Show when={error()}><p class="error">{error()}</p></Show>
        <div class="settings-form-group">
          <label>{t("migration.targetLabel")}</label>
          <input
            type="text"
            value={targetApId()}
            onInput={(e) => setTargetApId(e.currentTarget.value)}
            placeholder={t("migration.targetPlaceholder")}
          />
        </div>
        <button
          class="btn btn-small btn-danger"
          onClick={handleMove}
          disabled={migrating() || !targetApId().trim()}
        >
          {migrating() ? t("common.loading") : t("migration.move")}
        </button>
      </div>
    </AuthGuard>
  );
}
