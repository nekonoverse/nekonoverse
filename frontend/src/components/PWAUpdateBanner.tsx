import { createSignal, onMount, Show } from "solid-js";
import { useI18n } from "../i18n";

export default function PWAUpdateBanner() {
  const { t } = useI18n();
  const [needRefresh, setNeedRefresh] = createSignal(false);
  let updateSW: ((reloadPage?: boolean) => Promise<void>) | undefined;

  onMount(async () => {
    try {
      const { registerSW } = await import("virtual:pwa-register");
      updateSW = registerSW({
        onNeedRefresh() {
          setNeedRefresh(true);
        },
      });
    } catch {
      // SW registration not available (dev mode)
    }
  });

  const handleUpdate = () => {
    updateSW?.(true);
  };

  return (
    <Show when={needRefresh()}>
      <div class="pwa-update-banner">
        <span>{t("pwa.updateAvailable")}</span>
        <button onClick={handleUpdate}>{t("pwa.reload")}</button>
      </div>
    </Show>
  );
}
