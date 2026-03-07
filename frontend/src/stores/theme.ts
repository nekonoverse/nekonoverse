import { createSignal } from "solid-js";

export type Theme = "dark" | "light" | "novel";
export type FontSize = "small" | "medium" | "large" | "xlarge" | "xxlarge";

const THEMES: Theme[] = ["dark", "light", "novel"];
const FONT_SIZES: FontSize[] = ["small", "medium", "large", "xlarge", "xxlarge"];
const FONT_SIZE_MAP: Record<FontSize, string> = {
  small: "14px",
  medium: "16px",
  large: "20px",
  xlarge: "24px",
  xxlarge: "28px",
};

function loadTheme(): Theme {
  const saved = localStorage.getItem("theme");
  if (saved && THEMES.includes(saved as Theme)) return saved as Theme;
  return "dark";
}

function loadFontSize(): FontSize {
  const saved = localStorage.getItem("fontSize");
  if (saved && FONT_SIZES.includes(saved as FontSize)) return saved as FontSize;
  return "medium";
}

function applyTheme(t: Theme) {
  if (t === "dark") {
    document.documentElement.removeAttribute("data-theme");
  } else {
    document.documentElement.setAttribute("data-theme", t);
  }
}

function applyFontSize(s: FontSize) {
  document.documentElement.style.setProperty("--font-size-base", FONT_SIZE_MAP[s]);
}

const [theme, setThemeSignal] = createSignal<Theme>(loadTheme());
const [fontSize, setFontSizeSignal] = createSignal<FontSize>(loadFontSize());

export { theme, fontSize };

export function setTheme(t: Theme) {
  setThemeSignal(t);
  localStorage.setItem("theme", t);
  applyTheme(t);
}

export function setFontSize(s: FontSize) {
  setFontSizeSignal(s);
  localStorage.setItem("fontSize", s);
  applyFontSize(s);
}

export function initTheme() {
  applyTheme(theme());
  applyFontSize(fontSize());
}
