import { createSignal, onMount, Show, createMemo } from "solid-js";
import { useI18n } from "@nekonoverse/ui/i18n";
import { versionUpdateReady, applyUpdate } from "@nekonoverse/ui/stores/instance";

export default function PWAUpdateBanner() {
  const { t } = useI18n();
  const [swNeedRefresh, setSwNeedRefresh] = createSignal(false);
  let updateSW: ((reloadPage?: boolean) => Promise<void>) | undefined;

  onMount(async () => {
    try {
      const { registerSW } = await import("virtual:pwa-register");
      updateSW = registerSW({
        onNeedRefresh() {
          setSwNeedRefresh(true);
        },
      });
    } catch {
      // SW registration not available (dev mode)
    }
  });

  const showBanner = createMemo(() => swNeedRefresh() || versionUpdateReady());

  const handleUpdate = async () => {
    if (swNeedRefresh()) {
      updateSW?.(true);
    } else {
      await applyUpdate();
    }
  };

  return (
    <Show when={showBanner()}>
      <div class="pwa-update-banner">
        <span>{t("pwa.updateAvailable")}</span>
        <button onClick={handleUpdate}>{t("pwa.reload")}</button>
      </div>
    </Show>
  );
}
