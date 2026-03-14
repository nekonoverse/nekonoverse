import { describe, it, expect, beforeEach } from "vitest";
import { getRecentEmojis, addRecentEmoji, type RecentEmoji } from "./recentEmojis";

describe("getRecentEmojis", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("returns empty array when no history", () => {
    expect(getRecentEmojis()).toEqual([]);
  });

  it("returns stored emojis", () => {
    const emojis: RecentEmoji[] = [
      { emoji: "\u{1F600}", isCustom: false },
    ];
    localStorage.setItem("nekonoverse:recent-emojis", JSON.stringify(emojis));
    expect(getRecentEmojis()).toEqual(emojis);
  });

  it("returns empty array for invalid JSON", () => {
    localStorage.setItem("nekonoverse:recent-emojis", "not-json");
    expect(getRecentEmojis()).toEqual([]);
  });

  it("returns empty array for non-array JSON", () => {
    localStorage.setItem("nekonoverse:recent-emojis", JSON.stringify({ foo: "bar" }));
    expect(getRecentEmojis()).toEqual([]);
  });

  it("limits to 20 entries", () => {
    const emojis: RecentEmoji[] = Array.from({ length: 25 }, (_, i) => ({
      emoji: `emoji-${i}`,
      isCustom: false,
    }));
    localStorage.setItem("nekonoverse:recent-emojis", JSON.stringify(emojis));
    expect(getRecentEmojis()).toHaveLength(20);
  });
});

describe("addRecentEmoji", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("adds emoji to front of list", () => {
    addRecentEmoji({ emoji: "\u{1F600}", isCustom: false });
    addRecentEmoji({ emoji: "\u{1F601}", isCustom: false });
    const result = getRecentEmojis();
    expect(result[0].emoji).toBe("\u{1F601}");
    expect(result[1].emoji).toBe("\u{1F600}");
  });

  it("removes duplicates", () => {
    addRecentEmoji({ emoji: "\u{1F600}", isCustom: false });
    addRecentEmoji({ emoji: "\u{1F601}", isCustom: false });
    addRecentEmoji({ emoji: "\u{1F600}", isCustom: false });
    const result = getRecentEmojis();
    expect(result).toHaveLength(2);
    expect(result[0].emoji).toBe("\u{1F600}");
    expect(result[1].emoji).toBe("\u{1F601}");
  });

  it("trims to 20 entries", () => {
    for (let i = 0; i < 25; i++) {
      addRecentEmoji({ emoji: `emoji-${i}`, isCustom: false });
    }
    expect(getRecentEmojis()).toHaveLength(20);
  });

  it("stores custom emoji with url and shortcode", () => {
    const custom: RecentEmoji = {
      emoji: ":blobcat:",
      isCustom: true,
      url: "https://example.com/blobcat.png",
      shortcode: "blobcat",
    };
    addRecentEmoji(custom);
    const result = getRecentEmojis();
    expect(result[0]).toEqual(custom);
  });
});
