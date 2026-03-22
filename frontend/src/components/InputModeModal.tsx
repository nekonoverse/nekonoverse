import { useI18n } from "@nekonoverse/ui/i18n";
import { setInputMode, type InputMode } from "@nekonoverse/ui/stores/theme";

interface Props {
  onClose: () => void;
}

function detectTouchDevice(): boolean {
  return typeof window !== "undefined"
    && (("ontouchstart" in window) || window.matchMedia("(hover: none)").matches);
}

export default function InputModeModal(props: Props) {
  const { t } = useI18n();
  const recommended: InputMode = detectTouchDevice() ? "touch" : "pc";

  const select = (mode: InputMode) => {
    setInputMode(mode);
    props.onClose();
  };

  return (
    <div class="modal-overlay">
      <div class="modal-content" style="max-width: 400px">
        <div class="modal-header">
          <h3>{t("inputModeModal.title" as any)}</h3>
        </div>
        <div style="padding: 16px">
          <p style="color: var(--text-secondary); margin: 0 0 16px">
            {t("inputModeModal.description" as any)}
          </p>
          <div class="theme-selector" style="flex-direction: column; gap: 8px">
            <button
              class={`theme-btn${recommended === "pc" ? " theme-active" : ""}`}
              onClick={() => select("pc")}
              style="width: 100%; justify-content: center"
            >
              PC {recommended === "pc" && `(${t("inputModeModal.recommended" as any)})`}
            </button>
            <button
              class={`theme-btn${recommended === "touch" ? " theme-active" : ""}`}
              onClick={() => select("touch")}
              style="width: 100%; justify-content: center"
            >
              {t("settings.inputModeTouch" as any)} {recommended === "touch" && `(${t("inputModeModal.recommended" as any)})`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
