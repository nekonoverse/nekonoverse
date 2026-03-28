/**
 * Mastodon のフォーカルポイント (x, y) を CSS object-position に変換する。
 *
 * フォーカルポイント: x [-1..1] (左..右), y [-1..1] (下..上)
 * CSS object-position: x [0%..100%] (左..右), y [0%..100%] (上..下)
 */
export function focalPointToObjectPosition(
  focus: { x: number; y: number } | undefined | null,
): string | undefined {
  if (!focus) return undefined;
  const x = ((focus.x + 1) / 2) * 100;
  const y = ((1 - focus.y) / 2) * 100;
  return `${x.toFixed(1)}% ${y.toFixed(1)}%`;
}
