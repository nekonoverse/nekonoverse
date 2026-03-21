import { createSignal, onMount, onCleanup, Show } from "solid-js";
import type { MediaAttachment } from "@nekonoverse/ui/api/statuses";
import { useI18n } from "@nekonoverse/ui/i18n";

interface Props {
  media: MediaAttachment[];
  initialIndex: number;
  onClose: () => void;
}

export default function ImageLightbox(props: Props) {
  const { t } = useI18n();
  const [index, setIndex] = createSignal(props.initialIndex);
  const [scale, setScale] = createSignal(1);
  const [translate, setTranslate] = createSignal({ x: 0, y: 0 });
  const [dragging, setDragging] = createSignal(false);

  let dragStart = { x: 0, y: 0 };
  let translateStart = { x: 0, y: 0 };
  let lastTap = 0;
  let initialPinchDist = 0;
  let initialPinchScale = 1;
  let touchDidZoom = false;

  const current = () => props.media[index()];

  const resetZoom = () => {
    setScale(1);
    setTranslate({ x: 0, y: 0 });
  };

  const prev = () => {
    if (index() > 0) {
      setIndex(index() - 1);
      resetZoom();
    }
  };

  const next = () => {
    if (index() < props.media.length - 1) {
      setIndex(index() + 1);
      resetZoom();
    }
  };

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Escape") closeWithHistory();
    else if (e.key === "ArrowLeft") prev();
    else if (e.key === "ArrowRight") next();
  };

  let savedScrollY = 0;
  let pushedState = false;

  const handlePopState = () => {
    pushedState = false;
    props.onClose();
  };

  const closeWithHistory = () => {
    if (pushedState) {
      pushedState = false;
      history.back();
    }
    props.onClose();
  };

  onMount(() => {
    document.addEventListener("keydown", handleKeyDown);
    window.addEventListener("popstate", handlePopState);
    history.pushState({ lightbox: true }, "");
    pushedState = true;
    // モバイルで position: fixed のズレを防ぐ body 固定テクニック
    savedScrollY = window.scrollY;
    document.body.style.position = "fixed";
    document.body.style.top = `-${savedScrollY}px`;
    document.body.style.width = "100%";
    document.body.style.overflow = "hidden";
  });

  onCleanup(() => {
    document.removeEventListener("keydown", handleKeyDown);
    window.removeEventListener("popstate", handlePopState);
    if (pushedState) {
      pushedState = false;
      history.back();
    }
    document.body.style.position = "";
    document.body.style.top = "";
    document.body.style.width = "";
    document.body.style.overflow = "";
    window.scrollTo(0, savedScrollY);
  });

  const handleBackdropClick = (e: MouseEvent) => {
    if (scale() > 1) return;
    if ((e.target as HTMLElement).classList.contains("lightbox-overlay")) {
      closeWithHistory();
    }
  };

  const handleDoubleClick = (e: MouseEvent) => {
    // タッチのダブルタップで既にズーム済みならスキップ（合成dblclick回避）
    if (touchDidZoom) return;
    e.preventDefault();
    if (scale() > 1) {
      resetZoom();
    } else {
      setScale(2);
      setTranslate({ x: 0, y: 0 });
    }
  };

  const handleMouseDown = (e: MouseEvent) => {
    if (scale() <= 1) return;
    e.preventDefault();
    setDragging(true);
    dragStart = { x: e.clientX, y: e.clientY };
    translateStart = { ...translate() };

    const onMouseMove = (ev: MouseEvent) => {
      setTranslate({
        x: translateStart.x + (ev.clientX - dragStart.x),
        y: translateStart.y + (ev.clientY - dragStart.y),
      });
    };
    const onMouseUp = () => {
      setDragging(false);
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
  };

  const handleTouchStart = (e: TouchEvent) => {
    if (e.touches.length === 2) {
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      initialPinchDist = Math.sqrt(dx * dx + dy * dy);
      initialPinchScale = scale();
    } else if (e.touches.length === 1) {
      const now = Date.now();
      if (now - lastTap < 300) {
        e.preventDefault();
        if (scale() > 1) {
          resetZoom();
        } else {
          setScale(2);
          setTranslate({ x: 0, y: 0 });
        }
        // 合成 dblclick イベントでズームが戻るのを防ぐ
        touchDidZoom = true;
        setTimeout(() => { touchDidZoom = false; }, 400);
      }
      lastTap = now;

      if (scale() > 1) {
        dragStart = { x: e.touches[0].clientX, y: e.touches[0].clientY };
        translateStart = { ...translate() };
        setDragging(true);
      }
    }
  };

  const handleTouchMove = (e: TouchEvent) => {
    if (e.touches.length === 2) {
      e.preventDefault();
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      const dist = Math.sqrt(dx * dx + dy * dy);
      const newScale = Math.min(5, Math.max(1, initialPinchScale * (dist / initialPinchDist)));
      setScale(newScale);
      if (newScale <= 1) setTranslate({ x: 0, y: 0 });
    } else if (e.touches.length === 1 && dragging()) {
      e.preventDefault();
      setTranslate({
        x: translateStart.x + (e.touches[0].clientX - dragStart.x),
        y: translateStart.y + (e.touches[0].clientY - dragStart.y),
      });
    }
  };

  const handleTouchEnd = () => {
    setDragging(false);
    if (scale() < 1) resetZoom();
  };

  const openExternal = () => {
    window.open(current().url, "_blank", "noopener,noreferrer");
  };

  const isPWA = () => window.matchMedia("(display-mode: standalone)").matches;

  return (
    <div class="lightbox-overlay" onClick={handleBackdropClick}>
      <button class="lightbox-close" onClick={closeWithHistory} aria-label="Close">
        &times;
      </button>

      <div class="lightbox-toolbar">
        <Show when={isPWA()}>
          <button class="lightbox-tool-btn" onClick={openExternal} title={t("lightbox.openExternal")}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
              <polyline points="15 3 21 3 21 9" />
              <line x1="10" y1="14" x2="21" y2="3" />
            </svg>
          </button>
        </Show>
        <span class="lightbox-counter">
          {index() + 1} / {props.media.length}
        </span>
      </div>

      <Show when={props.media.length > 1 && index() > 0}>
        <button class="lightbox-nav lightbox-nav-prev" onClick={prev} aria-label="Previous">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </button>
      </Show>

      <Show when={current().type === "video"} fallback={
        <div
          class="lightbox-image-container"
          onDblClick={handleDoubleClick}
          onMouseDown={handleMouseDown}
          onTouchStart={handleTouchStart}
          onTouchMove={handleTouchMove}
          onTouchEnd={handleTouchEnd}
        >
          <img
            src={current().url}
            alt={current().description || ""}
            class="lightbox-image"
            draggable={false}
            style={{
              transform: `scale(${scale()}) translate(${translate().x / scale()}px, ${translate().y / scale()}px)`,
              cursor: scale() > 1 ? (dragging() ? "grabbing" : "grab") : "default",
            }}
          />
        </div>
      }>
        <div class="lightbox-image-container">
          <video
            src={current().url}
            class="lightbox-video"
            controls
            autoplay
            playsinline
          />
        </div>
      </Show>

      <Show when={props.media.length > 1 && index() < props.media.length - 1}>
        <button class="lightbox-nav lightbox-nav-next" onClick={next} aria-label="Next">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="9 18 15 12 9 6" />
          </svg>
        </button>
      </Show>

      <Show when={current().description}>
        <div class="lightbox-alt">{current().description}</div>
      </Show>
    </div>
  );
}
