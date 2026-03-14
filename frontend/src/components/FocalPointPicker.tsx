import { createSignal } from "solid-js";
import { useI18n } from "@nekonoverse/ui/i18n";

interface Props {
  imageUrl: string;
  initialX?: number;
  initialY?: number;
  onSave: (x: number, y: number) => void;
  onClose: () => void;
}

export default function FocalPointPicker(props: Props) {
  const { t } = useI18n();
  const [x, setX] = createSignal(props.initialX ?? 0);
  const [y, setY] = createSignal(props.initialY ?? 0);
  let containerRef!: HTMLDivElement;

  const updateFromEvent = (e: MouseEvent) => {
    const rect = containerRef.getBoundingClientRect();
    const px = (e.clientX - rect.left) / rect.width;
    const py = (e.clientY - rect.top) / rect.height;
    setX(Math.max(-1, Math.min(1, px * 2 - 1)));
    setY(Math.max(-1, Math.min(1, 1 - py * 2)));
  };

  const handleMouseDown = (e: MouseEvent) => {
    e.preventDefault();
    updateFromEvent(e);
    const onMove = (ev: MouseEvent) => updateFromEvent(ev);
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  };

  // Convert focal point to CSS percentage for marker position
  const markerLeft = () => `${((x() + 1) / 2) * 100}%`;
  const markerTop = () => `${((1 - y()) / 2) * 100}%`;

  return (
    <div class="focal-point-overlay" onClick={() => props.onClose()}>
      <div class="focal-point-dialog" onClick={(e) => e.stopPropagation()}>
        <div class="focal-point-header">
          <span>{t("composer.focalPoint")}</span>
          <button type="button" class="focal-point-close" onClick={() => props.onClose()}>
            &#x2715;
          </button>
        </div>
        <div
          ref={containerRef}
          class="focal-point-image-container"
          onMouseDown={handleMouseDown}
        >
          <img src={props.imageUrl} alt="" draggable={false} />
          <div
            class="focal-point-marker"
            style={{
              left: markerLeft(),
              top: markerTop(),
            }}
          />
        </div>
        <div class="focal-point-footer">
          <span class="focal-point-coords">
            x: {x().toFixed(2)}, y: {y().toFixed(2)}
          </span>
          <button
            type="button"
            class="focal-point-save-btn"
            onClick={() => props.onSave(x(), y())}
          >
            {t("composer.saveFocalPoint")}
          </button>
        </div>
      </div>
    </div>
  );
}
