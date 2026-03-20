import { createSignal, createEffect, onMount, Show, For, Switch, Match } from "solid-js";
import QRCode from "qrcode";
import { useNavigate, useParams, A } from "@solidjs/router";
import { currentUser, authLoading, logout } from "@nekonoverse/ui/stores/auth";
import {
  theme, setTheme, fontSize, setFontSize,
  fontFamily, setFontFamily, customFontFamily, setCustomFontFamily,
  timeFormat, setTimeFormat,
  cursorStyle, setCursorStyle,
  hideNonFollowedReplies, setHideNonFollowedReplies,
  nyaizeEnabled, setNyaizeEnabled,
  FONT_FAMILY_MAP,
  type Theme, type FontSize, type FontFamily, type TimeFormat, type CursorStyle,
} from "@nekonoverse/ui/stores/theme";
import {
  defaultVisibility, setDefaultVisibility,
  rememberVisibility, setRememberVisibility,
} from "@nekonoverse/ui/stores/composer";
import { instance, defaultAvatar, clearServiceWorkerAndCaches } from "@nekonoverse/ui/stores/instance";
import VisibilitySelector from "../components/notes/VisibilitySelector";
import { useI18n, locales, type Locale } from "@nekonoverse/ui/i18n";
import { changePassword } from "@nekonoverse/ui/api/settings";
import { getAuthorizedApps, revokeAuthorizedApp, type AuthorizedApp } from "@nekonoverse/ui/api/authorizedApps";
import { getBlockedAccounts, unblockAccount, getMutedAccounts, unmuteAccount, moveAccount, type Account } from "@nekonoverse/ui/api/accounts";
import { setupTotp, enableTotp, disableTotp, getTotpStatus } from "@nekonoverse/ui/api/totp";
import PasskeyManager from "../components/PasskeyManager";
import Breadcrumb from "../components/Breadcrumb";

declare const __APP_VERSION__: string;

interface SettingsSection {
  key: string;
  labelKey: string;
  descKey: string;
}

interface SettingsCategory {
  labelKey: string;
  sections: SettingsSection[];
}

const categories: SettingsCategory[] = [
  {
    labelKey: "settings.categoryGeneral",
    sections: [
      { key: "posting", labelKey: "settings.tabPosting", descKey: "settings.descPosting" },
      { key: "appearance", labelKey: "settings.tabAppearance", descKey: "settings.descAppearance" },
    ],
  },
  {
    labelKey: "settings.categoryAccount",
    sections: [
      { key: "security", labelKey: "settings.tabSecurity", descKey: "settings.descSecurity" },
      { key: "apps", labelKey: "settings.tabApps", descKey: "settings.descApps" },
      { key: "blocks", labelKey: "settings.tabBlocks", descKey: "settings.descBlocks" },
      { key: "mutes", labelKey: "settings.tabMutes", descKey: "settings.descMutes" },
      { key: "migration", labelKey: "settings.tabMigration", descKey: "settings.descMigration" },
    ],
  },
  {
    labelKey: "settings.categorySystem",
    sections: [
      { key: "about", labelKey: "settings.tabAbout", descKey: "settings.descAbout" },
    ],
  },
];

function findSectionLabel(t: (key: any) => string, sectionKey: string): string {
  for (const cat of categories) {
    for (const s of cat.sections) {
      if (s.key === sectionKey) return t(s.labelKey as any);
    }
  }
  return "";
}

export default function Settings() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const params = useParams<{ section?: string }>();

  const section = () => params.section || "";

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <div class="page-container">
      <Show when={section()} fallback={
        <>
          <h1>{t("settings.title")}</h1>
          <div class="settings-menu">
            <For each={categories}>
              {(cat) => (
                <div class="settings-menu-category">
                  <h3 class="settings-menu-category-title">{t(cat.labelKey as any)}</h3>
                  <div class="settings-menu-grid">
                    <For each={cat.sections}>
                      {(s) => (
                        <A href={`/settings/${s.key}`} class="settings-menu-card">
                          <span class="settings-menu-card-title">{t(s.labelKey as any)}</span>
                          <span class="settings-menu-card-desc">{t(s.descKey as any)}</span>
                        </A>
                      )}
                    </For>
                  </div>
                </div>
              )}
            </For>
          </div>
        </>
      }>
        <Breadcrumb items={[
          { label: t("settings.title"), href: "/settings" },
          { label: findSectionLabel(t, section()) },
        ]} />
        <Switch>
          <Match when={section() === "posting"}><PostingTab /></Match>
          <Match when={section() === "appearance"}><AppearanceTab /></Match>
          <Match when={section() === "security"}><SecurityTab onLogout={handleLogout} /></Match>
          <Match when={section() === "apps"}><AppsTab /></Match>
          <Match when={section() === "blocks"}><BlocksTab /></Match>
          <Match when={section() === "mutes"}><MutesTab /></Match>
          <Match when={section() === "migration"}><MigrationTab /></Match>
          <Match when={section() === "about"}><AboutTab /></Match>
        </Switch>
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
            { key: "small" as FontSize, size: "14px" },
            { key: "medium" as FontSize, size: "16px" },
            { key: "large" as FontSize, size: "20px" },
            { key: "xlarge" as FontSize, size: "24px" },
            { key: "xxlarge" as FontSize, size: "28px" },
          ]).map((item) => (
            <button
              class={`theme-btn${fontSize() === item.key ? " theme-active" : ""}`}
              style={{ "font-size": item.size }}
              onClick={() => setFontSize(item.key)}
            >
              {t("settings.fontSample" as any)}
            </button>
          ))}
        </div>
      </div>

      <div class="settings-section">
        <h3>{t("settings.fontFamily")}</h3>
        <div class="theme-selector">
          {([
            { key: "noto" as FontFamily, label: t("settings.fontNoto"), css: FONT_FAMILY_MAP.noto },
            { key: "hiragino" as FontFamily, label: t("settings.fontHiragino"), css: FONT_FAMILY_MAP.hiragino },
            { key: "yu-mac" as FontFamily, label: t("settings.fontYuMac"), css: FONT_FAMILY_MAP["yu-mac"] },
            { key: "yu-win" as FontFamily, label: t("settings.fontYuWin"), css: FONT_FAMILY_MAP["yu-win"] },
            { key: "meiryo" as FontFamily, label: t("settings.fontMeiryo"), css: FONT_FAMILY_MAP.meiryo },
            { key: "ipa" as FontFamily, label: t("settings.fontIPA"), css: FONT_FAMILY_MAP.ipa },
            { key: "system" as FontFamily, label: t("settings.fontSystem"), css: FONT_FAMILY_MAP.system },
            { key: "custom" as FontFamily, label: t("settings.fontCustom"), css: undefined },
          ]).map((item) => (
            <button
              class={`theme-btn${fontFamily() === item.key ? " theme-active" : ""}`}
              style={item.css ? { "font-family": item.css } : {}}
              onClick={() => setFontFamily(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <Show when={fontFamily() === "custom"}>
          <input
            type="text"
            class="font-custom-input"
            placeholder={t("settings.fontCustomPlaceholder")}
            value={customFontFamily()}
            onInput={(e) => setCustomFontFamily(e.currentTarget.value)}
            style={{ "font-family": customFontFamily() || "inherit" }}
          />
          <p class="settings-desc" style={{ "margin-top": "4px" }}>{t("settings.fontCustomHint")}</p>
        </Show>
      </div>

      <div class="settings-section">
        <h3>{t("settings.timeFormat")}</h3>
        <div class="theme-selector">
          {([
            { key: "absolute" as TimeFormat, label: t("settings.timeAbsolute") },
            { key: "relative" as TimeFormat, label: t("settings.timeRelative") },
            { key: "combined" as TimeFormat, label: t("settings.timeCombined") },
            { key: "unixtime" as TimeFormat, label: t("settings.timeUnixtime") },
          ]).map((item) => (
            <button
              class={`theme-btn${timeFormat() === item.key ? " theme-active" : ""}`}
              onClick={() => setTimeFormat(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div class="settings-section">
        <h3>{t("settings.cursorStyle")}</h3>
        <div class="theme-selector">
          {([
            { key: "default" as CursorStyle, label: t("settings.cursorDefault") },
            { key: "paw" as CursorStyle, label: t("settings.cursorPaw") },
          ]).map((item) => (
            <button
              class={`theme-btn${cursorStyle() === item.key ? " theme-active" : ""}`}
              onClick={() => setCursorStyle(item.key)}
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
        exclude={["direct"]}
      />
      <label class="toggle-label">
        <input
          type="checkbox"
          checked={rememberVisibility()}
          onChange={(e) => setRememberVisibility(e.currentTarget.checked)}
        />
        {t("settings.rememberVisibility")}
      </label>
      <h3>{t("settings.timeline")}</h3>
      <label class="toggle-label">
        <input
          type="checkbox"
          checked={hideNonFollowedReplies()}
          onChange={(e) => setHideNonFollowedReplies(e.currentTarget.checked)}
        />
        {t("settings.hideNonFollowedReplies")}
      </label>
      <label class="toggle-label">
        <input
          type="checkbox"
          checked={nyaizeEnabled()}
          onChange={(e) => setNyaizeEnabled(e.currentTarget.checked)}
        />
        {t("settings.nyaize")}
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

  // TOTP state
  const [totpEnabled, setTotpEnabled] = createSignal(false);
  const [totpLoading, setTotpLoading] = createSignal(true);
  const [totpStep, setTotpStep] = createSignal<
    "idle" | "qr" | "verify" | "recovery" | "disable"
  >("idle");
  const [totpSecret, setTotpSecret] = createSignal("");
  const [totpUri, setTotpUri] = createSignal("");
  const [totpCode, setTotpCode] = createSignal("");
  const [recoveryCodes, setRecoveryCodes] = createSignal<string[]>([]);
  const [totpError, setTotpError] = createSignal("");
  const [totpProcessing, setTotpProcessing] = createSignal(false);
  const [disablePw, setDisablePw] = createSignal("");
  const [setupPw, setSetupPw] = createSignal("");
  const [qrDataUrl, setQrDataUrl] = createSignal("");

  createEffect(async () => {
    const uri = totpUri();
    if (uri) {
      try {
        const dataUrl = await QRCode.toDataURL(uri, { width: 200, margin: 2 });
        setQrDataUrl(dataUrl);
      } catch {
        setQrDataUrl("");
      }
    } else {
      setQrDataUrl("");
    }
  });

  onMount(async () => {
    try {
      const status = await getTotpStatus();
      setTotpEnabled(status.totp_enabled);
    } catch {}
    setTotpLoading(false);
  });

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

  const handleSetupTotp = async () => {
    if (!setupPw()) {
      setTotpError(t("totp.passwordRequired"));
      return;
    }
    setTotpError("");
    setTotpProcessing(true);
    try {
      const data = await setupTotp(setupPw());
      setSetupPw("");
      setTotpSecret(data.secret);
      setTotpUri(data.provisioning_uri);
      setTotpStep("qr");
    } catch (e: any) {
      setTotpError(e.message);
    } finally {
      setTotpProcessing(false);
    }
  };

  const handleEnableTotp = async () => {
    setTotpError("");
    setTotpProcessing(true);
    try {
      const data = await enableTotp(totpCode());
      setRecoveryCodes(data.recovery_codes);
      setTotpStep("recovery");
      setTotpEnabled(true);
    } catch (e: any) {
      setTotpError(e.message);
    } finally {
      setTotpProcessing(false);
    }
  };

  const handleDisableTotp = async () => {
    setTotpError("");
    setTotpProcessing(true);
    try {
      await disableTotp(disablePw());
      setTotpEnabled(false);
      setTotpStep("idle");
      setDisablePw("");
    } catch (e: any) {
      setTotpError(e.message);
    } finally {
      setTotpProcessing(false);
    }
  };

  const handleCopySecret = () => {
    navigator.clipboard.writeText(totpSecret());
  };

  const handleCopyRecovery = () => {
    navigator.clipboard.writeText(recoveryCodes().join("\n"));
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
        <h3>{t("totp.title")}</h3>
        <Show when={!totpLoading()} fallback={<p>{t("common.loading")}</p>}>
          <Show when={totpError()}><p class="error">{totpError()}</p></Show>

          <Switch>
            <Match when={totpStep() === "idle" && !totpEnabled()}>
              <p class="settings-desc">{t("totp.description")}</p>
              <div class="form-group">
                <label>{t("totp.confirmPassword")}</label>
                <input
                  type="password"
                  value={setupPw()}
                  onInput={(e) => setSetupPw(e.currentTarget.value)}
                  placeholder={t("totp.confirmPassword")}
                />
              </div>
              <button
                class="btn btn-small"
                onClick={handleSetupTotp}
                disabled={totpProcessing() || !setupPw()}
              >
                {t("totp.enable")}
              </button>
            </Match>

            <Match when={totpStep() === "qr"}>
              <p>{t("totp.scanQr")}</p>
              <div class="totp-qr-section">
                <Show when={qrDataUrl()}>
                  <img
                    src={qrDataUrl()}
                    alt="TOTP QR Code"
                    class="totp-qr-image"
                    width="200"
                    height="200"
                  />
                </Show>
                <div class="totp-secret-display">
                  <code>{totpSecret()}</code>
                  <button
                    class="btn btn-small"
                    onClick={handleCopySecret}
                  >
                    {t("totp.copySecret")}
                  </button>
                </div>
              </div>
              <div class="settings-form-group">
                <label>{t("totp.enterCode")}</label>
                <input
                  type="text"
                  inputMode="numeric"
                  maxLength={6}
                  value={totpCode()}
                  onInput={(e) => setTotpCode(e.currentTarget.value)}
                  placeholder="000000"
                />
              </div>
              <div class="totp-actions">
                <button
                  class="btn btn-small"
                  onClick={handleEnableTotp}
                  disabled={totpProcessing() || totpCode().length < 6}
                >
                  {t("totp.verify")}
                </button>
                <button
                  class="btn btn-small"
                  onClick={() => { setTotpStep("idle"); setTotpError(""); }}
                >
                  {t("common.cancel")}
                </button>
              </div>
            </Match>

            <Match when={totpStep() === "recovery"}>
              <p class="totp-recovery-warning">{t("totp.recoveryWarning")}</p>
              <div class="totp-recovery-codes">
                <For each={recoveryCodes()}>
                  {(code) => <code class="totp-recovery-code">{code}</code>}
                </For>
              </div>
              <div class="totp-actions">
                <button class="btn btn-small" onClick={handleCopyRecovery}>
                  {t("totp.copyCodes")}
                </button>
                <button
                  class="btn btn-small"
                  onClick={() => {
                    setTotpStep("idle");
                    setRecoveryCodes([]);
                    setTotpCode("");
                    setTotpError("");
                  }}
                >
                  {t("totp.saved")}
                </button>
              </div>
            </Match>

            <Match when={totpStep() === "idle" && totpEnabled()}>
              <p class="settings-success">{t("totp.enabled")}</p>
              <button
                class="btn btn-small btn-danger"
                onClick={() => setTotpStep("disable")}
              >
                {t("totp.disable")}
              </button>
            </Match>

            <Match when={totpStep() === "disable"}>
              <p>{t("totp.disableConfirm")}</p>
              <div class="settings-form-group">
                <label>{t("auth.password")}</label>
                <input
                  type="password"
                  value={disablePw()}
                  onInput={(e) => setDisablePw(e.currentTarget.value)}
                />
              </div>
              <div class="totp-actions">
                <button
                  class="btn btn-small btn-danger"
                  onClick={handleDisableTotp}
                  disabled={totpProcessing() || !disablePw()}
                >
                  {t("totp.disable")}
                </button>
                <button
                  class="btn btn-small"
                  onClick={() => {
                    setTotpStep("idle");
                    setDisablePw("");
                    setTotpError("");
                  }}
                >
                  {t("common.cancel")}
                </button>
              </div>
            </Match>
          </Switch>
        </Show>
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

function AppsTab() {
  const { t } = useI18n();
  const [apps, setApps] = createSignal<AuthorizedApp[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [revokeTarget, setRevokeTarget] = createSignal<AuthorizedApp | null>(null);
  const [revoking, setRevoking] = createSignal(false);

  onMount(async () => {
    try {
      setApps(await getAuthorizedApps());
    } catch {}
    setLoading(false);
  });

  const handleRevoke = async () => {
    const target = revokeTarget();
    if (!target) return;
    setRevoking(true);
    try {
      await revokeAuthorizedApp(target.id);
      setApps((prev) => prev.filter((a) => a.id !== target.id));
      setRevokeTarget(null);
    } catch {}
    setRevoking(false);
  };

  return (
    <AuthGuard>
      <div class="settings-section">
        <h3>{t("apps.authorizedApps" as any)}</h3>
        <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
          <Show when={apps().length > 0} fallback={<p class="empty">{t("apps.noApps" as any)}</p>}>
            <div class="blockmute-list">
              <For each={apps()}>
                {(app) => (
                  <div class="blockmute-item">
                    <div class="blockmute-user" style={{ cursor: "default" }}>
                      <div>
                        <strong>{app.name}</strong>
                        <Show when={app.website && /^https?:\/\//.test(app.website!)}>
                          <a
                            href={app.website!}
                            target="_blank"
                            rel="noopener noreferrer"
                            class="blockmute-handle"
                          >
                            {app.website}
                          </a>
                        </Show>
                        <span class="blockmute-handle">
                          {app.scopes.join(", ")}
                        </span>
                        <span class="blockmute-handle">
                          {t("apps.authorizedAt" as any)}: {new Date(app.created_at).toLocaleDateString()}
                        </span>
                      </div>
                    </div>
                    <button class="btn btn-small btn-danger" onClick={() => setRevokeTarget(app)}>
                      {t("apps.revoke" as any)}
                    </button>
                  </div>
                )}
              </For>
            </div>
          </Show>
        </Show>
      </div>
      <Show when={revokeTarget()}>
        <div class="modal-overlay" onClick={() => setRevokeTarget(null)}>
          <div class="modal-content" style={{ padding: "24px", "max-width": "400px" }} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: "0 0 8px" }}>{t("apps.confirmRevoke" as any)}</h3>
            <p style={{ margin: "0 0 20px", color: "var(--text-secondary)" }}>{revokeTarget()!.name}</p>
            <div style={{ display: "flex", gap: "8px", "justify-content": "flex-end" }}>
              <button class="btn btn-small" onClick={() => setRevokeTarget(null)}>
                {t("common.cancel")}
              </button>
              <button class="btn btn-small btn-danger" onClick={handleRevoke} disabled={revoking()}>
                {t("apps.revoke" as any)}
              </button>
            </div>
          </div>
        </div>
      </Show>
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
                      <img class="blockmute-avatar" src={acc.avatar || defaultAvatar()} alt="" />
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
                      <img class="blockmute-avatar" src={acc.avatar || defaultAvatar()} alt="" />
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

function AboutTab() {
  const { t } = useI18n();
  const [clearing, setClearing] = createSignal(false);

  const handleClearCache = async () => {
    setClearing(true);
    try {
      await clearServiceWorkerAndCaches();
      location.reload();
    } catch {
      setClearing(false);
    }
  };

  const info = () => instance();

  return (
    <>
      <div class="settings-section">
        <h3>{t("about.serverInfo")}</h3>
        <div class="about-info-grid">
          <Show when={info()}>
            <div class="about-info-row">
              <span class="about-info-label">{t("about.serverName")}</span>
              <span class="about-info-value">{info()!.title}</span>
            </div>
            <Show when={info()!.description}>
              <div class="about-info-row">
                <span class="about-info-label">{t("about.description")}</span>
                <span class="about-info-value">{info()!.description}</span>
              </div>
            </Show>
            <div class="about-info-row">
              <span class="about-info-label">{t("about.domain")}</span>
              <span class="about-info-value">{info()!.uri}</span>
            </div>
          </Show>
        </div>
      </div>

      <div class="settings-section">
        <h3>{t("about.versionInfo")}</h3>
        <div class="about-info-grid">
          <div class="about-info-row">
            <span class="about-info-label">{t("about.backendVersion")}</span>
            <span class="about-info-value">{info()?.version ?? "—"}</span>
          </div>
          <div class="about-info-row">
            <span class="about-info-label">{t("about.frontendVersion")}</span>
            <span class="about-info-value">{__APP_VERSION__}</span>
          </div>
        </div>
      </div>

      <div class="settings-section">
        <p class="legal-links">
          <a href="/terms" target="_blank">{t("legal.terms")}</a>
          {" ・ "}
          <a href="/privacy" target="_blank">{t("legal.privacy")}</a>
        </p>
      </div>

      <div class="settings-section">
        <h3>{t("about.clearCache")}</h3>
        <p class="settings-desc">{t("about.clearCacheDesc")}</p>
        <button
          class="btn btn-small"
          onClick={handleClearCache}
          disabled={clearing()}
        >
          {clearing() ? t("about.cacheClearing") : t("about.clearCache")}
        </button>
      </div>
    </>
  );
}
