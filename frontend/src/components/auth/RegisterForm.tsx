import { createSignal, createEffect, on, onMount, onCleanup, Show } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { register } from "@nekonoverse/ui/stores/auth";
import { checkUsernameAvailable } from "@nekonoverse/ui/api/accounts";
import { turnstileSiteKey } from "@nekonoverse/ui/stores/instance";
import { useI18n } from "@nekonoverse/ui/i18n";

declare global {
  interface Window {
    turnstile?: {
      render: (container: string | HTMLElement, options: Record<string, unknown>) => string;
      remove: (widgetId: string) => void;
      getResponse: (widgetId: string) => string | undefined;
      reset: (widgetId: string) => void;
    };
  }
}

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
  const [usernameStatus, setUsernameStatus] = createSignal<"idle" | "checking" | "available" | "taken">("idle");
  const [captchaToken, setCaptchaToken] = createSignal("");

  let checkTimer: ReturnType<typeof setTimeout> | undefined;
  let turnstileWidgetId: string | undefined;
  let turnstileContainer: HTMLDivElement | undefined;

  createEffect(on(username, (val) => {
    clearTimeout(checkTimer);
    if (!val || !/^[a-zA-Z0-9_]+$/.test(val)) {
      setUsernameStatus("idle");
      return;
    }
    setUsernameStatus("checking");
    checkTimer = setTimeout(async () => {
      try {
        const available = await checkUsernameAvailable(val);
        // Only update if username hasn't changed during the request
        if (username() === val) {
          setUsernameStatus(available ? "available" : "taken");
        }
      } catch {
        if (username() === val) setUsernameStatus("idle");
      }
    }, 500);
  }));

  // Turnstile dynamic loading
  onMount(() => {
    const siteKey = turnstileSiteKey();
    if (!siteKey) return;

    const renderWidget = () => {
      if (!window.turnstile || !turnstileContainer) return;
      turnstileWidgetId = window.turnstile.render(turnstileContainer, {
        sitekey: siteKey,
        callback: (token: string) => setCaptchaToken(token),
        "expired-callback": () => setCaptchaToken(""),
      });
    };

    if (window.turnstile) {
      renderWidget();
    } else {
      if (!document.getElementById("cf-turnstile-script")) {
        const script = document.createElement("script");
        script.id = "cf-turnstile-script";
        script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
        script.async = true;
        script.onload = () => renderWidget();
        document.head.appendChild(script);
      } else {
        // Script already loading, poll for availability
        const poll = setInterval(() => {
          if (window.turnstile) {
            clearInterval(poll);
            renderWidget();
          }
        }, 100);
        onCleanup(() => clearInterval(poll));
      }
    }
  });

  onCleanup(() => {
    if (turnstileWidgetId && window.turnstile) {
      window.turnstile.remove(turnstileWidgetId);
    }
  });

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
        captchaToken() || undefined,
      );
      if (result.pending) {
        setPending(true);
      } else {
        navigate("/");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t("auth.registerFailed"));
      // Reset Turnstile widget on failure so user can retry
      if (turnstileWidgetId && window.turnstile) {
        window.turnstile.reset(turnstileWidgetId);
        setCaptchaToken("");
      }
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
            class={usernameStatus() === "taken" ? "input-error" : usernameStatus() === "available" ? "input-ok" : ""}
          />
          <Show when={usernameStatus() === "checking"}>
            <span class="field-hint">{t("auth.usernameChecking" as any)}</span>
          </Show>
          <Show when={usernameStatus() === "available"}>
            <span class="field-hint field-ok">{t("auth.usernameAvailable" as any)}</span>
          </Show>
          <Show when={usernameStatus() === "taken"}>
            <span class="field-hint field-error">{t("auth.usernameTaken" as any)}</span>
          </Show>
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
        <Show when={turnstileSiteKey()}>
          <div ref={turnstileContainer} class="turnstile-container" />
        </Show>
        <p class="legal-links">
          <a href="/terms" target="_blank">{t("legal.terms")}</a>
          {" ・ "}
          <a href="/privacy" target="_blank">{t("legal.privacy")}</a>
        </p>
        <button type="submit" disabled={loading() || usernameStatus() === "taken" || (!!turnstileSiteKey() && !captchaToken())}>
          {loading() ? t("auth.registering") : t("common.register")}
        </button>
        <p class="alt-action">
          {t("auth.hasAccount")} <a href="/login">{t("common.login")}</a>
        </p>
      </form>
    </Show>
  );
}
