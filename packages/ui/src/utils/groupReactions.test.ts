import { describe, it, expect } from "vitest";
import { groupReactions, extractShortcode } from "./groupReactions";
import type { ReactionSummary } from "../api/statuses";

function reaction(
  emoji: string,
  count: number,
  emoji_url: string | null = null,
  me = false,
  importable = false,
  import_domain?: string,
): ReactionSummary {
  return { emoji, count, me, emoji_url, importable, import_domain };
}

describe("extractShortcode", () => {
  it("extracts shortcode from local emoji", () => {
    expect(extractShortcode(":blobcat:")).toBe("blobcat");
  });
  it("extracts shortcode from remote emoji", () => {
    expect(extractShortcode(":blobcat@remote.example:")).toBe("blobcat");
  });
  it("returns null for unicode emoji", () => {
    expect(extractShortcode("👍")).toBeNull();
  });
  it("returns null for malformed strings", () => {
    expect(extractShortcode("blobcat")).toBeNull();
    expect(extractShortcode(":blobcat")).toBeNull();
  });
});

describe("groupReactions", () => {
  const emptyMap = new Map<string, string>();

  describe("unicode emoji", () => {
    it("groups same unicode emoji", () => {
      const groups = groupReactions(
        [reaction("👍", 3), reaction("👍", 2)],
        emptyMap,
      );
      expect(groups).toHaveLength(1);
      expect(groups[0].count).toBe(5);
    });

    it("keeps different unicode emoji separate", () => {
      const groups = groupReactions(
        [reaction("👍", 1), reaction("🎉", 1)],
        emptyMap,
      );
      expect(groups).toHaveLength(2);
    });
  });

  describe("shortcode-based grouping (Phase 1)", () => {
    it("groups same shortcode across local and remote", () => {
      const groups = groupReactions(
        [
          reaction(":blobcat:", 2, "https://local/blobcat.png"),
          reaction(":blobcat@remote.example:", 1, "https://remote/blobcat.png"),
        ],
        emptyMap,
      );
      expect(groups).toHaveLength(1);
      expect(groups[0].count).toBe(3);
    });

    it("prefers local emoji for display", () => {
      const groups = groupReactions(
        [
          reaction(":blobcat@remote.example:", 1, "https://remote/blobcat.png"),
          reaction(":blobcat:", 2, "https://local/blobcat.png"),
        ],
        emptyMap,
      );
      expect(groups).toHaveLength(1);
      expect(groups[0].displayEmoji).toBe(":blobcat:");
      expect(groups[0].displayUrl).toBe("https://local/blobcat.png");
    });

    it("groups three domains with same shortcode", () => {
      const groups = groupReactions(
        [
          reaction(":cat:", 1, "https://a/cat.png"),
          reaction(":cat@b.example:", 1, "https://b/cat.png"),
          reaction(":cat@c.example:", 1, "https://c/cat.png"),
        ],
        emptyMap,
      );
      expect(groups).toHaveLength(1);
      expect(groups[0].count).toBe(3);
    });

    it("keeps different shortcodes separate without phash", () => {
      const groups = groupReactions(
        [
          reaction(":cat:", 1, "https://local/cat.png"),
          reaction(":dog:", 1, "https://local/dog.png"),
        ],
        emptyMap,
      );
      expect(groups).toHaveLength(2);
    });
  });

  describe("phash-based grouping (Phase 2)", () => {
    it("merges different shortcodes when phash matches", () => {
      const hashMap = new Map([
        ["https://local/cat.png", "abcdef0123456789"],
        ["https://local/dog.png", "abcdef0123456789"],
      ]);
      const groups = groupReactions(
        [
          reaction(":cat:", 1, "https://local/cat.png"),
          reaction(":dog:", 1, "https://local/dog.png"),
        ],
        hashMap,
      );
      expect(groups).toHaveLength(1);
      expect(groups[0].count).toBe(2);
    });

    it("keeps different shortcodes separate when phash differs", () => {
      const hashMap = new Map([
        ["https://local/cat.png", "0000000000000000"],
        ["https://local/dog.png", "ffffffffffffffff"],
      ]);
      const groups = groupReactions(
        [
          reaction(":cat:", 1, "https://local/cat.png"),
          reaction(":dog:", 1, "https://local/dog.png"),
        ],
        hashMap,
      );
      expect(groups).toHaveLength(2);
    });
  });

  describe("me flag propagation", () => {
    it("sets me when merging shortcode groups", () => {
      const groups = groupReactions(
        [
          reaction(":blobcat:", 1, "https://local/blobcat.png", false),
          reaction(":blobcat@remote:", 1, "https://remote/blobcat.png", true),
        ],
        emptyMap,
      );
      expect(groups).toHaveLength(1);
      expect(groups[0].me).toBe(true);
      expect(groups[0].myEmoji).toBe(":blobcat@remote:");
    });
  });

  describe("importable flag", () => {
    it("marks group importable when remote emoji has no local copy", () => {
      const groups = groupReactions(
        [reaction(":cat@remote:", 1, "https://remote/cat.png", false, true, "remote")],
        emptyMap,
      );
      expect(groups).toHaveLength(1);
      expect(groups[0].importable).toBe(true);
      expect(groups[0].importDomain).toBe("remote");
    });

    it("clears importable when local emoji is in group", () => {
      const groups = groupReactions(
        [
          reaction(":cat@remote:", 1, "https://remote/cat.png", false, true, "remote"),
          reaction(":cat:", 1, "https://local/cat.png"),
        ],
        emptyMap,
      );
      expect(groups).toHaveLength(1);
      expect(groups[0].importable).toBe(false);
    });
  });

  describe("edge cases", () => {
    it("handles custom emoji without URL", () => {
      const groups = groupReactions(
        [reaction(":unknown:", 1, null)],
        emptyMap,
      );
      expect(groups).toHaveLength(1);
    });

    it("handles empty reactions", () => {
      const groups = groupReactions([], emptyMap);
      expect(groups).toHaveLength(0);
    });

    it("handles mixed unicode and custom emoji", () => {
      const groups = groupReactions(
        [
          reaction("👍", 5),
          reaction(":blobcat:", 2, "https://local/blobcat.png"),
          reaction("🎉", 1),
          reaction(":blobcat@remote:", 1, "https://remote/blobcat.png"),
        ],
        emptyMap,
      );
      expect(groups).toHaveLength(3); // 👍, :blobcat: group, 🎉
    });
  });
});
