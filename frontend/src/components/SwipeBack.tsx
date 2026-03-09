import { createSignal, onCleanup, Show } from "solid-js";

// Detect touch-primary device (no hover capability)
const isTouchDevice = () =>
  typeof window !== "undefined" &&
  (("ontouchstart" in window) || window.matchMedia("(hover: none)").matches);

const EDGE_ZONE = 25;       // px from left edge
const THRESHOLD = 100;      // px to trigger back
const ANGLE_LIMIT = 30;     // degrees — horizontal lock

export default function SwipeBack() {
  if (!isTouchDevice()) return null;

  const [active, setActive] = createSignal(false);
  const [offsetX, setOffsetX] = createSignal(0);
  const [ready, setReady] = createSignal(false);

  let startX = 0;
  let startY = 0;
  let locked: "horizontal" | "vertical" | null = null;

  const isBlocked = () =>
    !!document.querySelector(".lightbox-overlay, .modal-overlay");

  const onTouchStart = (e: TouchEvent) => {
    if (isBlocked()) return;
    const touch = e.touches[0];
    if (touch.clientX > EDGE_ZONE) return;
    startX = touch.clientX;
    startY = touch.clientY;
    locked = null;
    setActive(true);
    setOffsetX(0);
    setReady(false);
  };

  const onTouchMove = (e: TouchEvent) => {
    if (!active()) return;
    const touch = e.touches[0];
    const dx = touch.clientX - startX;
    const dy = touch.clientY - startY;

    // Determine direction on first significant move
    if (locked === null) {
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < 10) return;
      const angle = Math.atan2(Math.abs(dy), Math.abs(dx)) * (180 / Math.PI);
      locked = angle <= ANGLE_LIMIT ? "horizontal" : "vertical";
      if (locked === "vertical") {
        setActive(false);
        return;
      }
    }

    const clamped = Math.max(0, dx);
    setOffsetX(clamped);
    setReady(clamped >= THRESHOLD);
  };

  const onTouchEnd = () => {
    if (!active()) return;
    if (ready()) {
      history.back();
    }
    setActive(false);
    setOffsetX(0);
    setReady(false);
    locked = null;
  };

  document.addEventListener("touchstart", onTouchStart, { passive: true });
  document.addEventListener("touchmove", onTouchMove, { passive: true });
  document.addEventListener("touchend", onTouchEnd);

  onCleanup(() => {
    document.removeEventListener("touchstart", onTouchStart);
    document.removeEventListener("touchmove", onTouchMove);
    document.removeEventListener("touchend", onTouchEnd);
  });

  return (
    <Show when={active()}>
      <div
        class={`swipe-back-indicator${ready() ? " swipe-back-ready" : ""}`}
        style={{ transform: `translateX(${offsetX() - 20}px)` }}
      >
        ‹
      </div>
    </Show>
  );
}
