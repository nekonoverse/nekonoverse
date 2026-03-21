import { createSignal, Show } from "solid-js";
import { useI18n } from "@nekonoverse/ui/i18n";

export default function ForgotPassword() {
  const { t } = useI18n();
  const [email, setEmail] = createSignal("");
  const [loading, setLoading] = createSignal(false);
  const [sent, setSent] = createSignal(false);
  const [error, setError] = createSignal("");

  const handleSubmit = async (e: Event) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const resp = await fetch("/api/v1/auth/forgot-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email() }),
      });
      if (!resp.ok && resp.status !== 422) {
        const data = await resp.json().catch(() => ({}));
        setError(data.detail || "Failed to send reset email");
      } else if (resp.status === 422) {
        const data = await resp.json().catch(() => ({}));
        setError(data.detail || "Email is not configured on this server");
      } else {
        setSent(true);
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div class="page-container">
      <Show when={!sent()} fallback={
        <div class="auth-form">
          <h2>{t("auth.forgotPasswordTitle" as any)}</h2>
          <p class="settings-success">{t("auth.resetLinkSent" as any)}</p>
          <p class="alt-action">
            <a href="/login">{t("common.login" as any)}</a>
          </p>
        </div>
      }>
        <form onSubmit={handleSubmit} class="auth-form">
          <h2>{t("auth.forgotPasswordTitle" as any)}</h2>
          <p style={{ "margin-bottom": "16px", color: "var(--text-secondary)" }}>
            {t("auth.forgotPasswordDesc" as any)}
          </p>
          <Show when={error()}><div class="error">{error()}</div></Show>
          <div class="field">
            <label for="email">Email</label>
            <input
              id="email"
              type="email"
              value={email()}
              onInput={(e) => setEmail(e.currentTarget.value)}
              required
            />
          </div>
          <button type="submit" disabled={loading() || !email()}>
            {loading() ? "..." : t("auth.sendResetLink" as any)}
          </button>
          <p class="alt-action">
            <a href="/login">{t("common.login" as any)}</a>
          </p>
        </form>
      </Show>
    </div>
  );
}
