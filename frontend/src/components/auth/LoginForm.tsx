import { createSignal, Show } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { login, loginWithPasskey, completeTotpLogin } from "@nekonoverse/ui/stores/auth";
import { registrationMode } from "@nekonoverse/ui/stores/instance";
import { useI18n } from "@nekonoverse/ui/i18n";

export default function LoginForm() {
  const { t } = useI18n();
  const [username, setUsername] = createSignal("");
  const [password, setPassword] = createSignal("");
  const [error, setError] = createSignal("");
  const [loading, setLoading] = createSignal(false);
  const [passkeyLoading, setPasskeyLoading] = createSignal(false);
  const navigate = useNavigate();

  // TOTP state
  const [totpRequired, setTotpRequired] = createSignal(false);
  const [totpToken, setTotpToken] = createSignal("");
  const [totpCode, setTotpCode] = createSignal("");
  const [totpLoading, setTotpLoading] = createSignal(false);

  const handleSubmit = async (e: Event) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const resp = await login(username(), password());
      if (resp.requires_totp && resp.totp_token) {
        setTotpRequired(true);
        setTotpToken(resp.totp_token);
      } else {
        navigate("/");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t("auth.loginFailed"));
    } finally {
      setLoading(false);
    }
  };

  const handleTotpSubmit = async (e: Event) => {
    e.preventDefault();
    setError("");
    setTotpLoading(true);
    try {
      await completeTotpLogin(totpCode(), totpToken());
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("auth.loginFailed"));
    } finally {
      setTotpLoading(false);
    }
  };

  const handlePasskeyLogin = async () => {
    setError("");
    setPasskeyLoading(true);
    try {
      await loginWithPasskey();
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("auth.passkeyFailed"));
    } finally {
      setPasskeyLoading(false);
    }
  };

  const isPasskeySupported = () =>
    typeof window !== "undefined" && typeof window.PublicKeyCredential !== "undefined";

  return (
    <Show when={!totpRequired()} fallback={
      <form onSubmit={handleTotpSubmit} class="auth-form">
        <h2>{t("totp.required")}</h2>
        {error() && <div class="error">{error()}</div>}
        <div class="field">
          <label for="totp-code">{t("totp.enterCode")}</label>
          <input
            id="totp-code"
            type="text"
            inputMode="numeric"
            autocomplete="one-time-code"
            maxLength={10}
            value={totpCode()}
            onInput={(e) => setTotpCode(e.currentTarget.value)}
            required
            autofocus
          />
        </div>
        <button type="submit" disabled={totpLoading() || !totpCode().trim()}>
          {totpLoading() ? t("auth.loggingIn") : t("totp.verify")}
        </button>
        <p class="totp-hint">{t("totp.recoveryHint")}</p>
      </form>
    }>
      <form onSubmit={handleSubmit} class="auth-form">
        <h2>{t("common.login")}</h2>
        {error() && <div class="error">{error()}</div>}
        <div class="field">
          <label for="username">{t("auth.username")}</label>
          <input
            id="username"
            type="text"
            value={username()}
            onInput={(e) => setUsername(e.currentTarget.value)}
            required
          />
        </div>
        <div class="field">
          <label for="password">{t("auth.password")}</label>
          <input
            id="password"
            type="password"
            value={password()}
            onInput={(e) => setPassword(e.currentTarget.value)}
            required
          />
        </div>
        <button type="submit" disabled={loading()}>
          {loading() ? t("auth.loggingIn") : t("common.login")}
        </button>
        <p class="alt-action" style={{ "margin-top": "4px", "font-size": "0.85em" }}>
          <a href="/forgot-password">{t("auth.forgotPassword" as any)}</a>
        </p>
        <Show when={isPasskeySupported()}>
          <div class="passkey-divider">
            <span>{t("auth.or")}</span>
          </div>
          <button
            type="button"
            class="btn-passkey"
            disabled={passkeyLoading()}
            onClick={handlePasskeyLogin}
          >
            {passkeyLoading() ? t("auth.authenticating") : t("auth.loginWithPasskey")}
          </button>
        </Show>
        <Show when={registrationMode() !== "closed"}>
          <p class="alt-action">
            {t("auth.noAccount")} <a href="/register">{t("common.register")}</a>
          </p>
        </Show>
      </form>
    </Show>
  );
}
