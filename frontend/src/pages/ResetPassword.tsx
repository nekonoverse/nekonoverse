import { createSignal, Show } from "solid-js";
import { useSearchParams } from "@solidjs/router";
import { useI18n } from "@nekonoverse/ui/i18n";

export default function ResetPassword() {
  const { t } = useI18n();
  const [params] = useSearchParams();
  const [password, setPassword] = createSignal("");
  const [confirm, setConfirm] = createSignal("");
  const [loading, setLoading] = createSignal(false);
  const [success, setSuccess] = createSignal(false);
  const [error, setError] = createSignal("");

  const handleSubmit = async (e: Event) => {
    e.preventDefault();
    setError("");

    if (password() !== confirm()) {
      setError(t("settings.passwordMismatch" as any));
      return;
    }
    if (password().length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }

    setLoading(true);
    try {
      const resp = await fetch("/api/v1/auth/reset-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          token: params.token || "",
          uid: params.uid || "",
          password: password(),
        }),
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        setError(data.detail || "Failed to reset password");
      } else {
        setSuccess(true);
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div class="page-container">
      <Show when={!success()} fallback={
        <div class="auth-form">
          <h2>{t("auth.resetPasswordTitle" as any)}</h2>
          <p class="settings-success">{t("auth.passwordResetSuccess" as any)}</p>
          <p class="alt-action">
            <a href="/login">{t("common.login" as any)}</a>
          </p>
        </div>
      }>
        <form onSubmit={handleSubmit} class="auth-form">
          <h2>{t("auth.resetPasswordTitle" as any)}</h2>
          <p style={{ "margin-bottom": "16px", color: "var(--text-secondary)" }}>
            {t("auth.resetPasswordDesc" as any)}
          </p>
          <Show when={error()}><div class="error">{error()}</div></Show>
          <div class="field">
            <label for="new-password">{t("settings.newPassword" as any)}</label>
            <input
              id="new-password"
              type="password"
              value={password()}
              onInput={(e) => setPassword(e.currentTarget.value)}
              required
              minLength={8}
            />
          </div>
          <div class="field">
            <label for="confirm-password">{t("settings.confirmPassword" as any)}</label>
            <input
              id="confirm-password"
              type="password"
              value={confirm()}
              onInput={(e) => setConfirm(e.currentTarget.value)}
              required
            />
          </div>
          <button type="submit" disabled={loading() || !password() || !confirm()}>
            {loading() ? "..." : t("auth.resetPassword" as any)}
          </button>
        </form>
      </Show>
    </div>
  );
}
