import { createSignal, Show } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { register } from "@nekonoverse/ui/stores/auth";
import { useI18n } from "@nekonoverse/ui/i18n";

interface RegisterFormProps {
  inviteRequired?: boolean;
  approvalRequired?: boolean;
}

export default function RegisterForm(props: RegisterFormProps) {
  const { t } = useI18n();
  const [username, setUsername] = createSignal("");
  const [email, setEmail] = createSignal("");
  const [password, setPassword] = createSignal("");
  const [inviteCode, setInviteCode] = createSignal("");
  const [reason, setReason] = createSignal("");
  const [error, setError] = createSignal("");
  const [loading, setLoading] = createSignal(false);
  const [pending, setPending] = createSignal(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: Event) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const result = await register(
        username(),
        email(),
        password(),
        inviteCode() || undefined,
        reason() || undefined,
      );
      if (result.pending) {
        setPending(true);
      } else {
        navigate("/");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t("auth.registerFailed"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Show
      when={!pending()}
      fallback={
        <div class="auth-form">
          <h2>{t("auth.registrationPending")}</h2>
          <p>{t("auth.registrationPendingDesc")}</p>
          <p class="alt-action">
            <a href="/login">{t("auth.backToLogin")}</a>
          </p>
        </div>
      }
    >
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
        <Show when={props.approvalRequired}>
          <p class="invite-notice">{t("auth.approvalNotice")}</p>
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
        <Show when={props.approvalRequired}>
          <div class="field">
            <label for="reason">{t("auth.reason")}</label>
            <textarea
              id="reason"
              value={reason()}
              onInput={(e) => setReason(e.currentTarget.value)}
              placeholder={t("auth.reasonPlaceholder")}
              maxLength={1000}
              rows={4}
              required
            />
          </div>
        </Show>
        <p class="legal-links">
          <a href="/terms" target="_blank">{t("legal.terms")}</a>
          {" ・ "}
          <a href="/privacy" target="_blank">{t("legal.privacy")}</a>
        </p>
        <button type="submit" disabled={loading()}>
          {loading() ? t("auth.registering") : t("common.register")}
        </button>
        <p class="alt-action">
          {t("auth.hasAccount")} <a href="/login">{t("common.login")}</a>
        </p>
      </form>
    </Show>
  );
}
