import { createSignal } from "solid-js";
import { apiRequest } from "./client";
import type { CustomEmoji as BaseCustomEmoji } from "../types/emoji";

export interface CustomEmoji extends BaseCustomEmoji {
  visible_in_picker: boolean;
  category: string | null;
  aliases: string[];
}

let cachedEmojis: CustomEmoji[] | null = null;

export async function getCustomEmojis(): Promise<CustomEmoji[]> {
  if (cachedEmojis) return cachedEmojis;
  const emojis = await apiRequest<CustomEmoji[]>("/api/v1/custom_emojis");
  cachedEmojis = emojis.filter((e) => e.visible_in_picker);
  return cachedEmojis;
}

export function clearEmojiCache() {
  cachedEmojis = null;
}

// Track shortcodes imported during this session so all ReactionBars
// can immediately suppress the importable badge without refetching.
const [importedShortcodes, setImportedShortcodes] = createSignal<Set<string>>(
  new Set(),
);
export { importedShortcodes };

export function markShortcodeImported(shortcode: string) {
  setImportedShortcodes((prev) => new Set(prev).add(shortcode));
}
