import { apiRequest } from "./client";

export interface CustomEmoji {
  shortcode: string;
  url: string;
  static_url: string;
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
