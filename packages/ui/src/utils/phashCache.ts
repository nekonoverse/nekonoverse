const STORAGE_KEY = "nekonoverse:phash-cache";
const MAX_ENTRIES = 500;

interface PhashCacheEntry {
  hash: string;
  ts: number;
}

type PhashCacheData = Record<string, PhashCacheEntry>;

// Module-level memory cache to avoid redundant localStorage JSON.parse
let memoryCache: Map<string, string> | null = null;

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

function ensureMemoryCache(): Map<string, string> {
  if (memoryCache) return memoryCache;
  const cache = loadCache();
  memoryCache = new Map<string, string>();
  for (const [url, entry] of Object.entries(cache)) {
    memoryCache.set(url, entry.hash);
  }
  return memoryCache;
}

export function getCachedPhash(url: string): string | null {
  return ensureMemoryCache().get(url) ?? null;
}

export function getAllCachedPhashes(): Map<string, string> {
  return new Map(ensureMemoryCache());
}

export function setCachedPhash(url: string, hash: string): void {
  ensureMemoryCache().set(url, hash);
  const cache = loadCache();
  cache[url] = { hash, ts: Date.now() };
  saveCache(cache);
}
