import { createSignal, onMount, Show } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { login } from "../../stores/auth";
import { fetchInstance, registrationOpen } from "../../stores/instance";
import { useI18n } from "../../i18n";

export default function LoginForm() {
  const { t } = useI18n();
  const [username, setUsername] = createSignal("");
  const [password, setPassword] = createSignal("");
  const [error, setError] = createSignal("");
  const [loading, setLoading] = createSignal(false);
  const navigate = useNavigate();

  onMount(() => {
    fetchInstance();
  });

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
      <Show when={registrationOpen()}>
        <p class="alt-action">
          {t("auth.noAccount")} <a href="/register">{t("common.register")}</a>
        </p>
      </Show>
    </form>
  );
}
