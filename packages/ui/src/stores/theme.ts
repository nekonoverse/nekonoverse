import { createSignal } from "solid-js";
import { apiRequest } from "../api/client";

export type Theme = "dark" | "light" | "novel";
export type FontSize = "small" | "medium" | "large" | "xlarge" | "xxlarge";
export type FontFamily = "noto" | "hiragino" | "yu-mac" | "yu-win" | "meiryo" | "ipa" | "system" | "custom";
export type TimeFormat = "absolute" | "relative" | "combined" | "unixtime";
export type CursorStyle = "default" | "paw";
export type WideEmojiStyle = "shrink" | "blur" | "overflow";
export type InputMode = "auto" | "touch" | "pc";

export interface ThemeColors {
  "bg-primary": string;
  "bg-secondary": string;
  "bg-card": string;
  "text-primary": string;
  "text-secondary": string;
  accent: string;
  "accent-hover": string;
  "accent-text": string;
  border: string;
  reblog: string;
  favourite: string;
}

export interface ThemeCustomization {
  base: Theme;
  colors: ThemeColors;
  name?: string;
}

export const COLOR_KEYS: (keyof ThemeColors)[] = [
  "bg-primary", "bg-secondary", "bg-card",
  "text-primary", "text-secondary",
  "accent", "accent-hover", "accent-text",
  "border", "reblog", "favourite",
];

export const PRESET_COLORS: Record<Theme, ThemeColors> = {
  dark: {
    "bg-primary": "#1a1a2e",
    "bg-secondary": "#16213e",
    "bg-card": "#0f3460",
    "text-primary": "#e0e0e0",
    "text-secondary": "#a0a0b0",
    "accent": "#e94560",
    "accent-hover": "#ff6b81",
    "accent-text": "#ffffff",
    "border": "#2a2a4a",
    "reblog": "#2ecc71",
    "favourite": "#f1c40f",
  },
  light: {
    "bg-primary": "#f0f0f0",
    "bg-secondary": "#ffffff",
    "bg-card": "#e4e4e4",
    "text-primary": "#1a1a1a",
    "text-secondary": "#555555",
    "accent": "#d63851",
    "accent-hover": "#b82e44",
    "accent-text": "#ffffff",
    "border": "#cccccc",
    "reblog": "#27ae60",
    "favourite": "#d4a017",
  },
  novel: {
    "bg-primary": "#eee3cd",
    "bg-secondary": "#f7f0e3",
    "bg-card": "#e0d3b8",
    "text-primary": "#2a2015",
    "text-secondary": "#5c4e3a",
    "accent": "#a04828",
    "accent-hover": "#c45e35",
    "accent-text": "#f7f0e3",
    "border": "#c8b898",
    "reblog": "#6b8e23",
    "favourite": "#c49b1a",
  },
};

const THEMES: Theme[] = ["dark", "light", "novel"];
const FONT_SIZES: FontSize[] = ["small", "medium", "large", "xlarge", "xxlarge"];
const FONT_FAMILIES: FontFamily[] = ["noto", "hiragino", "yu-mac", "yu-win", "meiryo", "ipa", "system", "custom"];
const TIME_FORMATS: TimeFormat[] = ["absolute", "relative", "combined", "unixtime"];
const CURSOR_STYLES: CursorStyle[] = ["default", "paw"];
const WIDE_EMOJI_STYLES: WideEmojiStyle[] = ["shrink", "blur", "overflow"];
const INPUT_MODES: InputMode[] = ["auto", "touch", "pc"];
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

function loadWideEmojiStyle(): WideEmojiStyle {
  const saved = localStorage.getItem("wideEmojiStyle");
  if (saved && WIDE_EMOJI_STYLES.includes(saved as WideEmojiStyle)) return saved as WideEmojiStyle;
  return "overflow";
}

function loadInputMode(): InputMode | null {
  const saved = localStorage.getItem("nekonoverse:input-mode");
  if (saved && INPUT_MODES.includes(saved as InputMode)) return saved as InputMode;
  return null;
}

function detectTouchDevice(): boolean {
  return typeof window !== "undefined"
    && (("ontouchstart" in window) || window.matchMedia("(hover: none)").matches);
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

function applyWideEmojiStyle(s: WideEmojiStyle) {
  if (s === "overflow") {
    document.documentElement.removeAttribute("data-wide-emoji");
  } else {
    document.documentElement.setAttribute("data-wide-emoji", s);
  }
}

const [theme, setThemeSignal] = createSignal<Theme>(loadTheme());
const [fontSize, setFontSizeSignal] = createSignal<FontSize>(loadFontSize());
const [fontFamily, setFontFamilySignal] = createSignal<FontFamily>(loadFontFamily());
const [customFontFamily, setCustomFontFamilySignal] = createSignal<string>(loadCustomFontFamily());
const [timeFormat, setTimeFormatSignal] = createSignal<TimeFormat>(loadTimeFormat());
const [cursorStyle, setCursorStyleSignal] = createSignal<CursorStyle>(loadCursorStyle());
const [wideEmojiStyle, setWideEmojiStyleSignal] = createSignal<WideEmojiStyle>(loadWideEmojiStyle());

const [inputMode, setInputModeSignal] = createSignal<InputMode | null>(loadInputMode());

const [hideNonFollowedReplies, setHideNonFollowedRepliesSignal] = createSignal<boolean>(
  localStorage.getItem("nekonoverse:hide-non-followed-replies") !== "false"
);

const [nyaizeEnabled, setNyaizeEnabledSignal] = createSignal<boolean>(
  localStorage.getItem("nekonoverse:nyaize") !== "false"
);

const [reduceMfmMotion, setReduceMfmMotionSignal] = createSignal<boolean>(
  localStorage.getItem("nekonoverse:reduce-mfm-motion") === "true"
);

const [cropShadow, setCropShadowSignal] = createSignal<boolean>(
  localStorage.getItem("nekonoverse:crop-shadow") !== "false"
);

const [katexRender, setKatexRenderSignal] = createSignal<boolean>(
  localStorage.getItem("nekonoverse:katex-render") !== "false"
);

function loadCustomColors(): ThemeColors | null {
  try {
    const saved = localStorage.getItem("themeCustomization");
    return saved ? JSON.parse(saved) : null;
  } catch {
    return null;
  }
}

const [customColors, setCustomColorsSignal] = createSignal<ThemeColors | null>(loadCustomColors());
const [customThemeName, setCustomThemeNameSignal] = createSignal<string>(
  localStorage.getItem("themeCustomizationName") || ""
);

export { theme, fontSize, fontFamily, customFontFamily, timeFormat, cursorStyle, wideEmojiStyle, inputMode, hideNonFollowedReplies, nyaizeEnabled, reduceMfmMotion, cropShadow, katexRender, customColors, customThemeName };

export function isTouchMode(): boolean {
  const mode = inputMode();
  if (mode === "touch") return true;
  if (mode === "pc") return false;
  return detectTouchDevice();
}

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

export function setWideEmojiStyle(s: WideEmojiStyle) {
  setWideEmojiStyleSignal(s);
  localStorage.setItem("wideEmojiStyle", s);
  applyWideEmojiStyle(s);
}

export function setInputMode(m: InputMode) {
  setInputModeSignal(m);
  localStorage.setItem("nekonoverse:input-mode", m);
}

export function setHideNonFollowedReplies(v: boolean) {
  setHideNonFollowedRepliesSignal(v);
  localStorage.setItem("nekonoverse:hide-non-followed-replies", String(v));
}

export function setNyaizeEnabled(v: boolean) {
  setNyaizeEnabledSignal(v);
  localStorage.setItem("nekonoverse:nyaize", String(v));
}

export function setReduceMfmMotion(v: boolean) {
  setReduceMfmMotionSignal(v);
  localStorage.setItem("nekonoverse:reduce-mfm-motion", String(v));
  applyReduceMfmMotion(v);
}

export function setCropShadow(v: boolean) {
  setCropShadowSignal(v);
  localStorage.setItem("nekonoverse:crop-shadow", String(v));
  applyCropShadow(v);
}

export function setKatexRender(v: boolean) {
  setKatexRenderSignal(v);
  localStorage.setItem("nekonoverse:katex-render", String(v));
}

function applyCustomColors(colors: ThemeColors | null) {
  const root = document.documentElement;
  if (!colors) {
    for (const key of COLOR_KEYS) {
      root.style.removeProperty(`--${key}`);
    }
    return;
  }
  for (const key of COLOR_KEYS) {
    root.style.setProperty(`--${key}`, colors[key]);
  }
}

export function setCustomColors(colors: ThemeColors | null) {
  setCustomColorsSignal(colors);
  if (colors) {
    localStorage.setItem("themeCustomization", JSON.stringify(colors));
  } else {
    localStorage.removeItem("themeCustomization");
  }
  applyCustomColors(colors);
}

export function setCustomThemeName(name: string) {
  setCustomThemeNameSignal(name);
  if (name) {
    localStorage.setItem("themeCustomizationName", name);
  } else {
    localStorage.removeItem("themeCustomizationName");
  }
}

export function clearCustomColors() {
  setCustomColors(null);
  setCustomThemeName("");
}

export async function syncThemeFromServer() {
  try {
    const prefs = await apiRequest<{
      theme_customization?: ThemeCustomization | null;
    }>("/api/v1/preferences", { method: "GET" });
    const tc = prefs.theme_customization;
    if (tc) {
      setTheme(tc.base);
      setCustomColors(tc.colors);
      setCustomThemeName(tc.name || "");
    }
  } catch {
    // Use local values on failure
  }
}

function applyReduceMfmMotion(v: boolean) {
  if (v) {
    document.documentElement.setAttribute("data-reduce-mfm-motion", "");
  } else {
    document.documentElement.removeAttribute("data-reduce-mfm-motion");
  }
}

function applyCropShadow(v: boolean) {
  if (v) {
    document.documentElement.removeAttribute("data-crop-shadow");
  } else {
    document.documentElement.setAttribute("data-crop-shadow", "off");
  }
}

export function initTheme() {
  applyTheme(theme());
  applyFontSize(fontSize());
  applyFontFamily(fontFamily(), customFontFamily());
  applyCursorStyle(cursorStyle());
  applyWideEmojiStyle(wideEmojiStyle());
  applyReduceMfmMotion(reduceMfmMotion());
  applyCropShadow(cropShadow());
  applyCustomColors(customColors());
}
