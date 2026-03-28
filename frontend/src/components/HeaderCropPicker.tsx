import { createSignal, onMount } from "solid-js";
import { useI18n } from "@nekonoverse/ui/i18n";

interface Props {
  imageUrl: string;
  initialX?: number;
  initialY?: number;
  onSave: (x: number, y: number) => void;
  onClose: () => void;
}

const HEADER_ASPECT = 3; // 幅:高さ ≈ 3:1

export default function HeaderCropPicker(props: Props) {
  const { t } = useI18n();
  let canvasRef!: HTMLDivElement;
  let imgRef!: HTMLImageElement;

  const [imgLoaded, setImgLoaded] = createSignal(false);
  const [displayW, setDisplayW] = createSignal(0);
  const [displayH, setDisplayH] = createSignal(0);
  const [cropY, setCropY] = createSignal(0);
  const [cropX, setCropX] = createSignal(0);
  const [cropW, setCropW] = createSignal(0);
  const [cropH, setCropH] = createSignal(0);

  const initCrop = () => {
    const dw = imgRef.clientWidth;
    const dh = imgRef.clientHeight;
    setDisplayW(dw);
    setDisplayH(dh);

    // 切り抜きウィンドウ: 幅は全幅、高さはアスペクト比で決定
    const cw = dw;
    const ch = Math.min(dh, dw / HEADER_ASPECT);
    setCropW(cw);
    setCropH(ch);

    // 既存のフォーカルポイントから初期化
    const ix = props.initialX ?? 0;
    const iy = props.initialY ?? 0;
    const centerX = ((ix + 1) / 2) * dw;
    const centerY = ((1 - iy) / 2) * dh;

    setCropX(Math.max(0, Math.min(dw - cw, centerX - cw / 2)));
    setCropY(Math.max(0, Math.min(dh - ch, centerY - ch / 2)));
    setImgLoaded(true);
  };

  const focalFromCrop = (): [number, number] => {
    const cx = cropX() + cropW() / 2;
    const cy = cropY() + cropH() / 2;
    const fx = Math.max(-1, Math.min(1, (cx / displayW()) * 2 - 1));
    const fy = Math.max(-1, Math.min(1, 1 - (cy / displayH()) * 2));
    return [fx, fy];
  };

  const previewPosition = () => {
    const [fx, fy] = focalFromCrop();
    const x = ((fx + 1) / 2) * 100;
    const y = ((1 - fy) / 2) * 100;
    return `${x.toFixed(1)}% ${y.toFixed(1)}%`;
  };

  const startDrag = (e: MouseEvent | TouchEvent) => {
    e.preventDefault();
    const clientY = "touches" in e ? e.touches[0].clientY : e.clientY;
    const clientX = "touches" in e ? e.touches[0].clientX : e.clientX;
    const startCropY = cropY();
    const startCropX = cropX();

    const onMove = (ev: MouseEvent | TouchEvent) => {
      const cy = "touches" in ev ? ev.touches[0].clientY : ev.clientY;
      const cx = "touches" in ev ? ev.touches[0].clientX : ev.clientX;
      const dy = cy - clientY;
      const dx = cx - clientX;
      setCropY(Math.max(0, Math.min(displayH() - cropH(), startCropY + dy)));
      setCropX(Math.max(0, Math.min(displayW() - cropW(), startCropX + dx)));
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.removeEventListener("touchmove", onMove);
      document.removeEventListener("touchend", onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    document.addEventListener("touchmove", onMove, { passive: false });
    document.addEventListener("touchend", onUp);
  };

  return (
    <div class="header-crop-overlay" onClick={() => props.onClose()}>
      <div class="header-crop-dialog" onClick={(e) => e.stopPropagation()}>
        <div class="header-crop-title">
          <span>{t("profile.cropHeader")}</span>
          <button type="button" class="focal-point-close" onClick={() => props.onClose()}>
            &#x2715;
          </button>
        </div>
        <div ref={canvasRef} class="header-crop-canvas">
          <img
            ref={imgRef}
            src={props.imageUrl}
            alt=""
            draggable={false}
            onLoad={initCrop}
          />
          {imgLoaded() && (
            <>
              <div
                class="header-crop-dimmer"
                style={{ top: "0", height: `${cropY()}px` }}
              />
              <div
                class="header-crop-dimmer"
                style={{
                  top: `${cropY() + cropH()}px`,
                  bottom: "0",
                }}
              />
              <div
                class="header-crop-dimmer"
                style={{
                  top: `${cropY()}px`,
                  height: `${cropH()}px`,
                  left: "0",
                  width: `${cropX()}px`,
                }}
              />
              <div
                class="header-crop-dimmer"
                style={{
                  top: `${cropY()}px`,
                  height: `${cropH()}px`,
                  left: `${cropX() + cropW()}px`,
                  right: "0",
                }}
              />
              <div
                class="header-crop-window"
                style={{
                  top: `${cropY()}px`,
                  left: `${cropX()}px`,
                  width: `${cropW()}px`,
                  height: `${cropH()}px`,
                }}
                onMouseDown={startDrag}
                onTouchStart={startDrag}
              />
            </>
          )}
        </div>
        <div class="header-crop-preview">
          <div class="header-crop-preview-label">{t("profile.cropPreview")}</div>
          <img
            class="header-crop-preview-img"
            src={props.imageUrl}
            alt=""
            style={{ "object-position": previewPosition() }}
          />
        </div>
        <div class="header-crop-footer">
          <button
            type="button"
            class="focal-point-save-btn"
            onClick={() => {
              const [fx, fy] = focalFromCrop();
              props.onSave(fx, fy);
            }}
          >
            {t("composer.saveFocalPoint")}
          </button>
        </div>
      </div>
    </div>
  );
}
