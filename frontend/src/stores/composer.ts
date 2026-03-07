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

const [defaultVisibility, setDefaultVisibilitySignal] = createSignal<Visibility>(
  loadVisibility("defaultVisibility", "public"),
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
