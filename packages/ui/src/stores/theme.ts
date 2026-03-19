import { createSignal } from "solid-js";

export type Theme = "dark" | "light" | "novel";
export type FontSize = "small" | "medium" | "large" | "xlarge" | "xxlarge";
export type FontFamily = "noto" | "hiragino" | "yu-mac" | "yu-win" | "meiryo" | "ipa" | "system" | "custom";
export type TimeFormat = "absolute" | "relative" | "combined" | "unixtime";
export type CursorStyle = "default" | "paw";

const THEMES: Theme[] = ["dark", "light", "novel"];
const FONT_SIZES: FontSize[] = ["small", "medium", "large", "xlarge", "xxlarge"];
const FONT_FAMILIES: FontFamily[] = ["noto", "hiragino", "yu-mac", "yu-win", "meiryo", "ipa", "system", "custom"];
const TIME_FORMATS: TimeFormat[] = ["absolute", "relative", "combined", "unixtime"];
const CURSOR_STYLES: CursorStyle[] = ["default", "paw"];
const FONT_SIZE_MAP: Record<FontSize, string> = {
  small: "14px",
  medium: "16px",
  large: "20px",
  xlarge: "24px",
  xxlarge: "28px",
};
export const FONT_FAMILY_MAP: Record<Exclude<FontFamily, "custom">, string> = {
  noto: '"Noto Sans JP", sans-serif',
  hiragino: '"Hiragino Kaku Gothic ProN", "Hiragino Sans", sans-serif',
  "yu-mac": '"YuGothic", "Yu Gothic", sans-serif',
  "yu-win": '"Yu Gothic Medium", "Yu Gothic", "Meiryo", sans-serif',
  meiryo: '"Meiryo", "メイリオ", sans-serif',
  ipa: '"IPAexGothic", "IPA Pゴシック", sans-serif',
  system: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
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

function loadFontFamily(): FontFamily {
  const saved = localStorage.getItem("fontFamily");
  if (saved && FONT_FAMILIES.includes(saved as FontFamily)) return saved as FontFamily;
  return "noto";
}

function loadCustomFontFamily(): string {
  return localStorage.getItem("customFontFamily") || "";
}

function loadTimeFormat(): TimeFormat {
  const saved = localStorage.getItem("timeFormat");
  if (saved && TIME_FORMATS.includes(saved as TimeFormat)) return saved as TimeFormat;
  return "absolute";
}

function loadCursorStyle(): CursorStyle {
  const saved = localStorage.getItem("cursorStyle");
  if (saved && CURSOR_STYLES.includes(saved as CursorStyle)) return saved as CursorStyle;
  return "default";
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

function applyFontFamily(f: FontFamily, custom?: string) {
  const value = f === "custom"
    ? (custom || "sans-serif")
    : FONT_FAMILY_MAP[f];
  document.documentElement.style.setProperty("--font-family", value);
}

function applyCursorStyle(s: CursorStyle) {
  if (s === "default") {
    document.documentElement.removeAttribute("data-cursor");
  } else {
    document.documentElement.setAttribute("data-cursor", s);
  }
}

const [theme, setThemeSignal] = createSignal<Theme>(loadTheme());
const [fontSize, setFontSizeSignal] = createSignal<FontSize>(loadFontSize());
const [fontFamily, setFontFamilySignal] = createSignal<FontFamily>(loadFontFamily());
const [customFontFamily, setCustomFontFamilySignal] = createSignal<string>(loadCustomFontFamily());
const [timeFormat, setTimeFormatSignal] = createSignal<TimeFormat>(loadTimeFormat());
const [cursorStyle, setCursorStyleSignal] = createSignal<CursorStyle>(loadCursorStyle());

const [hideNonFollowedReplies, setHideNonFollowedRepliesSignal] = createSignal<boolean>(
  localStorage.getItem("nekonoverse:hide-non-followed-replies") !== "false"
);

const [nyaizeEnabled, setNyaizeEnabledSignal] = createSignal<boolean>(
  localStorage.getItem("nekonoverse:nyaize") !== "false"
);

export { theme, fontSize, fontFamily, customFontFamily, timeFormat, cursorStyle, hideNonFollowedReplies, nyaizeEnabled };

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

export function setFontFamily(f: FontFamily) {
  setFontFamilySignal(f);
  localStorage.setItem("fontFamily", f);
  applyFontFamily(f, customFontFamily());
}

export function setCustomFontFamily(v: string) {
  setCustomFontFamilySignal(v);
  localStorage.setItem("customFontFamily", v);
  if (fontFamily() === "custom") {
    applyFontFamily("custom", v);
  }
}

export function setTimeFormat(f: TimeFormat) {
  setTimeFormatSignal(f);
  localStorage.setItem("timeFormat", f);
}

export function setCursorStyle(s: CursorStyle) {
  setCursorStyleSignal(s);
  localStorage.setItem("cursorStyle", s);
  applyCursorStyle(s);
}

export function setHideNonFollowedReplies(v: boolean) {
  setHideNonFollowedRepliesSignal(v);
  localStorage.setItem("nekonoverse:hide-non-followed-replies", String(v));
}

export function setNyaizeEnabled(v: boolean) {
  setNyaizeEnabledSignal(v);
  localStorage.setItem("nekonoverse:nyaize", String(v));
}

export function initTheme() {
  applyTheme(theme());
  applyFontSize(fontSize());
  applyFontFamily(fontFamily(), customFontFamily());
  applyCursorStyle(cursorStyle());
}
