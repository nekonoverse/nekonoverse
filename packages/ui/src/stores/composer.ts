import { createSignal } from "solid-js";

export type Visibility = "public" | "unlisted" | "followers" | "direct";

const VISIBILITIES: Visibility[] = ["public", "unlisted", "followers", "direct"];

function loadVisibility(key: string, fallback: Visibility): Visibility {
  const saved = localStorage.getItem(key);
  if (saved && VISIBILITIES.includes(saved as Visibility)) return saved as Visibility;
  return fallback;
}

function loadBool(key: string, fallback: boolean): boolean {
  const saved = localStorage.getItem(key);
  if (saved === "true") return true;
  if (saved === "false") return false;
  return fallback;
}

// "direct" is not a valid default visibility — migrate to "public" if set
const loadedDefault = loadVisibility("defaultVisibility", "public");
const [defaultVisibility, setDefaultVisibilitySignal] = createSignal<Visibility>(
  loadedDefault === "direct" ? "public" : loadedDefault,
);
const [rememberVisibility, setRememberVisibilitySignal] = createSignal<boolean>(
  loadBool("rememberVisibility", false),
);
const [lastVisibility, setLastVisibilitySignal] = createSignal<Visibility>(
  loadVisibility("lastVisibility", "public"),
);

export { defaultVisibility, rememberVisibility, lastVisibility };

export function setDefaultVisibility(v: Visibility) {
  setDefaultVisibilitySignal(v);
  localStorage.setItem("defaultVisibility", v);
}

export function setRememberVisibility(v: boolean) {
  setRememberVisibilitySignal(v);
  localStorage.setItem("rememberVisibility", String(v));
}

export function setLastVisibility(v: Visibility) {
  setLastVisibilitySignal(v);
  localStorage.setItem("lastVisibility", v);
}

/** Returns the visibility to use when opening the composer. */
export function getInitialVisibility(): Visibility {
  return rememberVisibility() ? lastVisibility() : defaultVisibility();
}

const VISIBILITY_RANK: Record<Visibility, number> = {
  public: 0,
  unlisted: 1,
  followers: 2,
  direct: 3,
};

/** Return the more restrictive of two visibilities. */
export function moreRestrictiveVisibility(a: Visibility, b: Visibility): Visibility {
  return (VISIBILITY_RANK[a] ?? 0) >= (VISIBILITY_RANK[b] ?? 0) ? a : b;
}

// --- Draft storage ---

export interface Draft {
  id: string;
  content: string;
  visibility: Visibility;
  createdAt: number;
}

const DRAFTS_KEY = "composerDrafts";

function loadDrafts(): Draft[] {
  try {
    const raw = localStorage.getItem(DRAFTS_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

const [drafts, setDraftsSignal] = createSignal<Draft[]>(loadDrafts());

export { drafts };

function persistDrafts(list: Draft[]) {
  setDraftsSignal(list);
  localStorage.setItem(DRAFTS_KEY, JSON.stringify(list));
}

export function saveDraft(content: string, visibility: Visibility): Draft {
  const draft: Draft = {
    id: crypto.randomUUID(),
    content,
    visibility,
    createdAt: Date.now(),
  };
  persistDrafts([draft, ...loadDrafts()]);
  return draft;
}

export function deleteDraft(id: string) {
  persistDrafts(loadDrafts().filter((d) => d.id !== id));
}

export function clearDrafts() {
  persistDrafts([]);
}
