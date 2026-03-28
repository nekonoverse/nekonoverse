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
  // 重複を除去
  const filtered = list.filter((e) => e.emoji !== entry.emoji);
  // 先頭に追加
  filtered.unshift(entry);
  // 上限まで切り詰め
  const trimmed = filtered.slice(0, MAX_RECENT);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
  } catch {
    // localStorage が満杯または利用不可 — 無視
  }
}
