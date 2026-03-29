/**
 * グローバルタッチガード: ロングプレスでモーダルが開いた後、指を離すまで
 * すべてのクリックイベントをキャプチャフェーズでブロックする。
 *
 * モバイルでは、ロングプレスでモーダルが指の下に表示された際、
 * 指を離すとモーダル要素へのクリックが合成される。
 * このユーティリティはそのゴーストタップを防止する。
 *
 * PCモードではゴーストタップが発生しないため、ガードは何もしない。
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

/** ロングプレスでモーダルを開いた際にゴーストタップをブロックするために呼び出す。 */
export function activateTouchGuard() {
  if (!isTouchMode()) return;
  removeGuard();

  guardHandler = (e: Event) => {
    e.stopPropagation();
    e.preventDefault();
  };
  document.addEventListener("click", guardHandler, { capture: true });

  const deactivate = () => {
    // touchend後に発火する合成クリックイベントをキャッチするための短い遅延
    cleanupTimer = setTimeout(removeGuard, 100);
  };

  touchEndHandler = deactivate;
  touchCancelHandler = deactivate;
  document.addEventListener("touchend", deactivate, { once: true });
  document.addEventListener("touchcancel", deactivate, { once: true });

  // 安全タイムアウト: touchendが発火しない場合に備え、1秒後に必ずガードを解除する
  // （例: PCでタッチエミュレーションによりロングプレスが発動するが、
  // タッチではなくマウスクリックで指を離した場合）
  safetyTimer = setTimeout(removeGuard, 1000);
}
