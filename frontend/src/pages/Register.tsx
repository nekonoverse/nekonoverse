import { onMount, Show } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { currentUser } from "@nekonoverse/ui/stores/auth";
import { registrationMode, inviteRequired, approvalRequired, instanceLoading } from "@nekonoverse/ui/stores/instance";
import { useI18n } from "@nekonoverse/ui/i18n";
import RegisterForm from "../components/auth/RegisterForm";

export default function Register() {
  const { t } = useI18n();
  const navigate = useNavigate();

  onMount(() => {
    if (currentUser()) {
      navigate("/", { replace: true });
    }
  });

  return (
    <div class="page-container">
      <Show when={!instanceLoading()} fallback={<p>{t("common.loading")}</p>}>
        <Show
          when={registrationMode() !== "closed"}
          fallback={
            <div class="auth-form">
              <h2>{t("auth.registrationClosed")}</h2>
              <p>{t("auth.registrationClosedDesc")}</p>
              <p class="alt-action">
                <a href="/login">{t("auth.backToLogin")}</a>
              </p>
            </div>
          }
        >
          <RegisterForm inviteRequired={inviteRequired()} approvalRequired={approvalRequired()} />
        </Show>
      </Show>
    </div>
  );
}
