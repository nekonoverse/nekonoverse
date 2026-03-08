import { createSignal, Show } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { register } from "../../stores/auth";
import { useI18n } from "../../i18n";

interface RegisterFormProps {
  inviteRequired?: boolean;
}

export default function RegisterForm(props: RegisterFormProps) {
  const { t } = useI18n();
  const [username, setUsername] = createSignal("");
  const [email, setEmail] = createSignal("");
  const [password, setPassword] = createSignal("");
  const [inviteCode, setInviteCode] = createSignal("");
  const [error, setError] = createSignal("");
  const [loading, setLoading] = createSignal(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: Event) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await register(username(), email(), password(), inviteCode() || undefined);
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("auth.registerFailed"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} class="auth-form">
      <h2>{t("common.register")}</h2>
      {error() && <div class="error">{error()}</div>}
      <Show when={props.inviteRequired}>
        <p class="invite-notice">{t("auth.inviteRequired")}</p>
        <div class="field">
          <label for="invite_code">{t("auth.inviteCode")}</label>
          <input
            id="invite_code"
            type="text"
            value={inviteCode()}
            onInput={(e) => setInviteCode(e.currentTarget.value)}
            placeholder={t("auth.inviteCodePlaceholder")}
            required
          />
        </div>
      </Show>
      <div class="field">
        <label for="username">{t("auth.username")}</label>
        <input
          id="username"
          type="text"
          value={username()}
          onInput={(e) => setUsername(e.currentTarget.value)}
          pattern="[a-zA-Z0-9_]+"
          required
        />
      </div>
      <div class="field">
        <label for="email">{t("auth.email")}</label>
        <input
          id="email"
          type="email"
          value={email()}
          onInput={(e) => setEmail(e.currentTarget.value)}
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
          minLength={8}
          required
        />
      </div>
      <button type="submit" disabled={loading()}>
        {loading() ? t("auth.registering") : t("common.register")}
      </button>
      <p class="alt-action">
        {t("auth.hasAccount")} <a href="/login">{t("common.login")}</a>
      </p>
    </form>
  );
}
