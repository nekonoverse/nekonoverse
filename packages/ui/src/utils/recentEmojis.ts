import type { RecentEmoji } from "../types/emoji";

export type { RecentEmoji };

const STORAGE_KEY = "nekonoverse:recent-emojis";
const MAX_RECENT = 20;

export function getRecentEmojis(): RecentEmoji[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.slice(0, MAX_RECENT);
  } catch {
    return [];
  }
}

export function addRecentEmoji(entry: RecentEmoji): void {
  const list = getRecentEmojis();
  // Remove duplicate
  const filtered = list.filter((e) => e.emoji !== entry.emoji);
  // Add to front
  filtered.unshift(entry);
  // Trim
  const trimmed = filtered.slice(0, MAX_RECENT);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
  } catch {
    // localStorage full or unavailable — ignore
  }
}
