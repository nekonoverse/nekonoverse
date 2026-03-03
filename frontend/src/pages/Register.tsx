import { onMount, Show } from "solid-js";
import { fetchInstance, registrationOpen, instanceLoading } from "../stores/instance";
import { useI18n } from "../i18n";
import RegisterForm from "../components/auth/RegisterForm";

export default function Register() {
  const { t } = useI18n();

  onMount(() => {
    fetchInstance();
  });

  return (
    <div class="page-container">
      <Show when={!instanceLoading()} fallback={<p>{t("common.loading")}</p>}>
        <Show
          when={registrationOpen()}
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
          <RegisterForm />
        </Show>
      </Show>
    </div>
  );
}
