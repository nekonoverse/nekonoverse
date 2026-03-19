const STORAGE_KEY = "nekonoverse:phash-cache";
const MAX_ENTRIES = 500;

interface PhashCacheEntry {
  hash: string;
  ts: number;
}

type PhashCacheData = Record<string, PhashCacheEntry>;

function loadCache(): PhashCacheData {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return {};
    return parsed as PhashCacheData;
  } catch {
    return {};
  }
}

function saveCache(cache: PhashCacheData): void {
  const entries = Object.entries(cache);
  if (entries.length > MAX_ENTRIES) {
    entries.sort((a, b) => a[1].ts - b[1].ts);
    cache = Object.fromEntries(entries.slice(entries.length - MAX_ENTRIES));
  }
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(cache));
  } catch {
    // localStorage full or unavailable
  }
}

export function getCachedPhash(url: string): string | null {
  const cache = loadCache();
  return cache[url]?.hash ?? null;
}

export function getAllCachedPhashes(): Map<string, string> {
  const cache = loadCache();
  const map = new Map<string, string>();
  for (const [url, entry] of Object.entries(cache)) {
    map.set(url, entry.hash);
  }
  return map;
}

export function setCachedPhash(url: string, hash: string): void {
  const cache = loadCache();
  cache[url] = { hash, ts: Date.now() };
  saveCache(cache);
}
