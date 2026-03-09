import { createSignal, Show } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { login, loginWithPasskey } from "../../stores/auth";
import { registrationOpen } from "../../stores/instance";
import { useI18n } from "../../i18n";

export default function LoginForm() {
  const { t } = useI18n();
  const [username, setUsername] = createSignal("");
  const [password, setPassword] = createSignal("");
  const [error, setError] = createSignal("");
  const [loading, setLoading] = createSignal(false);
  const [passkeyLoading, setPasskeyLoading] = createSignal(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: Event) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(username(), password());
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("auth.loginFailed"));
    } finally {
      setLoading(false);
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
      <Show when={registrationOpen()}>
        <p class="alt-action">
          {t("auth.noAccount")} <a href="/register">{t("common.register")}</a>
        </p>
      </Show>
    </form>
  );
}
