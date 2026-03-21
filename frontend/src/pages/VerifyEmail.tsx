import { createSignal, onMount } from "solid-js";
import { useSearchParams, useNavigate } from "@solidjs/router";
import { useI18n } from "@nekonoverse/ui/i18n";

export default function VerifyEmail() {
  const { t } = useI18n();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [status, setStatus] = createSignal<"loading" | "success" | "error">("loading");

  onMount(async () => {
    const token = params.token;
    const uid = params.uid;

    if (!token || !uid) {
      setStatus("error");
      return;
    }

    try {
      const resp = await fetch("/api/v1/email/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, uid }),
      });
      if (resp.ok) {
        setStatus("success");
        setTimeout(() => navigate("/", { replace: true }), 3000);
      } else {
        setStatus("error");
      }
    } catch {
      setStatus("error");
    }
  });

  return (
    <div class="page-container">
      <div class="auth-form" style={{ "text-align": "center" }}>
        {status() === "loading" && (
          <p>{t("auth.verifyingEmail" as any)}</p>
        )}
        {status() === "success" && (
          <p class="settings-success">{t("auth.emailVerified" as any)}</p>
        )}
        {status() === "error" && (
          <p class="error">{t("auth.emailVerifyFailed" as any)}</p>
        )}
      </div>
    </div>
  );
}
