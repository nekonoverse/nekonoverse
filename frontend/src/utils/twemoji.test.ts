import { describe, it, expect } from "vitest";
import { emojiToUrl } from "./twemoji";

const BASE = "https://cdn.jsdelivr.net/gh/jdecked/twemoji@latest/assets/svg";

describe("emojiToUrl", () => {
  it("converts a simple emoji to SVG URL", () => {
    // "A" codepoint for a simple smiley
    const url = emojiToUrl("\u{1f600}");
    expect(url).toBe(`${BASE}/1f600.svg`);
  });

  it("filters out variation selector fe0f", () => {
    // Red heart with variation selector: U+2764 U+FE0F
    const url = emojiToUrl("\u2764\uFE0F");
    expect(url).toBe(`${BASE}/2764.svg`);
  });

  it("handles multi-codepoint emoji (flag)", () => {
    // Japanese flag: U+1F1EF U+1F1F5
    const url = emojiToUrl("\u{1F1EF}\u{1F1F5}");
    expect(url).toBe(`${BASE}/1f1ef-1f1f5.svg`);
  });

  it("handles emoji with ZWJ sequence", () => {
    // Family: man, woman, girl, boy (ZWJ sequence)
    // U+1F468 U+200D U+1F469 U+200D U+1F467 U+200D U+1F466
    const url = emojiToUrl("\u{1F468}\u200D\u{1F469}\u200D\u{1F467}\u200D\u{1F466}");
    expect(url).toBe(`${BASE}/1f468-200d-1f469-200d-1f467-200d-1f466.svg`);
  });

  it("handles skin tone modifier", () => {
    // Waving hand + medium skin tone: U+1F44B U+1F3FD
    const url = emojiToUrl("\u{1F44B}\u{1F3FD}");
    expect(url).toBe(`${BASE}/1f44b-1f3fd.svg`);
  });
});
