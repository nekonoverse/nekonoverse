/**
 * Global touch guard: blocks all click events (at capture phase) after a
 * long-press opens a modal, until the user lifts their finger.
 *
 * On mobile, when a long-press triggers a modal that appears under the
 * finger, releasing the finger synthesizes a click on the modal element.
 * This utility prevents that ghost tap.
 *
 * In PC mode the guard is a no-op because ghost taps do not occur.
 */

import { isTouchMode } from "@nekonoverse/ui/stores/theme";

let guardHandler: ((e: Event) => void) | null = null;
let cleanupTimer: ReturnType<typeof setTimeout> | undefined;
let safetyTimer: ReturnType<typeof setTimeout> | undefined;
let touchEndHandler: (() => void) | null = null;
let touchCancelHandler: (() => void) | null = null;

function removeGuard() {
  if (guardHandler) {
    document.removeEventListener("click", guardHandler, true);
    guardHandler = null;
  }
  if (touchEndHandler) {
    document.removeEventListener("touchend", touchEndHandler);
    touchEndHandler = null;
  }
  if (touchCancelHandler) {
    document.removeEventListener("touchcancel", touchCancelHandler);
    touchCancelHandler = null;
  }
  if (cleanupTimer !== undefined) {
    clearTimeout(cleanupTimer);
    cleanupTimer = undefined;
  }
  if (safetyTimer !== undefined) {
    clearTimeout(safetyTimer);
    safetyTimer = undefined;
  }
}

/** Call this when a long-press opens a modal to block ghost taps. */
export function activateTouchGuard() {
  if (!isTouchMode()) return;
  removeGuard();

  guardHandler = (e: Event) => {
    e.stopPropagation();
    e.preventDefault();
  };
  document.addEventListener("click", guardHandler, { capture: true });

  const deactivate = () => {
    // Small delay to catch synthesized click events that fire after touchend
    cleanupTimer = setTimeout(removeGuard, 100);
  };

  touchEndHandler = deactivate;
  touchCancelHandler = deactivate;
  document.addEventListener("touchend", deactivate, { once: true });
  document.addEventListener("touchcancel", deactivate, { once: true });

  // Safety timeout: always remove the guard after 1s in case touchend never
  // fires (e.g. on PC where long-press is triggered by touch emulation but
  // the user releases via mouse click instead of touch).
  safetyTimer = setTimeout(removeGuard, 1000);
}
