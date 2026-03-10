/**
 * Convert Mastodon focal point (x, y) to CSS object-position.
 *
 * Focal point: x [-1..1] (left..right), y [-1..1] (bottom..top)
 * CSS object-position: x [0%..100%] (left..right), y [0%..100%] (top..bottom)
 */
export function focalPointToObjectPosition(
  focus: { x: number; y: number } | undefined | null,
): string | undefined {
  if (!focus) return undefined;
  const x = ((focus.x + 1) / 2) * 100;
  const y = ((1 - focus.y) / 2) * 100;
  return `${x.toFixed(1)}% ${y.toFixed(1)}%`;
}
