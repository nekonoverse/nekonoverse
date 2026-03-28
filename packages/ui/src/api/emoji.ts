import { createSignal } from "solid-js";
import { apiRequest } from "./client";
import type { CustomEmoji as BaseCustomEmoji } from "../types/emoji";
import { onEmojiUpdate } from "../stores/streaming";

export interface CustomEmoji extends BaseCustomEmoji {
  visible_in_picker: boolean;
  category: string | null;
  aliases: string[];
}

let cachedEmojis: CustomEmoji[] | null = null;
let lastFetchedAt = 0;
const EMOJI_CACHE_TTL = 5 * 60 * 1000; // 5分

export async function getCustomEmojis(): Promise<CustomEmoji[]> {
  const now = Date.now();
  if (cachedEmojis && now - lastFetchedAt < EMOJI_CACHE_TTL) {
    return cachedEmojis;
  }
  const emojis = await apiRequest<CustomEmoji[]>("/api/v1/custom_emojis");
  cachedEmojis = emojis.filter((e) => e.visible_in_picker);
  lastFetchedAt = now;
  return cachedEmojis;
}

export function clearEmojiCache() {
  cachedEmojis = null;
  lastFetchedAt = 0;
}

// このセッション中にインポートされたショートコードを追跡し、
// 全 ReactionBar が再取得なしで importable バッジを即座に抑制できるようにする。
const [importedShortcodes, setImportedShortcodes] = createSignal<Set<string>>(
  new Set(),
);
export { importedShortcodes };

export function markShortcodeImported(shortcode: string) {
  setImportedShortcodes((prev: Set<string>) => new Set(prev).add(shortcode));
}

// SSE経由で絵文字変更を即座に反映
// キャッシュクリア + 再取得して importable バッジを全クライアントで抑制
onEmojiUpdate(() => {
  clearEmojiCache();
  getCustomEmojis()
    .then((emojis) => {
      const shortcodes = new Set(emojis.map((e) => e.shortcode));
      setImportedShortcodes((prev: Set<string>) => {
        const merged = new Set(prev);
        for (const sc of shortcodes) merged.add(sc);
        return merged;
      });
    })
    .catch(() => {});
});
