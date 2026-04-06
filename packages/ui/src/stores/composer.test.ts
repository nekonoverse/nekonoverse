import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  moreRestrictiveVisibility,
  normalizeVisibility,
  VISIBILITY_RANK,
  type Visibility,
} from "./composer";

describe("VISIBILITY_RANK", () => {
  it("public < unlisted < followers < direct の順に制限が強い", () => {
    expect(VISIBILITY_RANK.public).toBeLessThan(VISIBILITY_RANK.unlisted);
    expect(VISIBILITY_RANK.unlisted).toBeLessThan(VISIBILITY_RANK.followers);
    expect(VISIBILITY_RANK.followers).toBeLessThan(VISIBILITY_RANK.direct);
  });
});

describe("normalizeVisibility", () => {
  it('"private" を "followers" に正規化する', () => {
    expect(normalizeVisibility("private")).toBe("followers");
  });

  it.each(["public", "unlisted", "followers", "direct"] as const)(
    '"%s" はそのまま返す',
    (v) => {
      expect(normalizeVisibility(v)).toBe(v);
    },
  );
});

describe("moreRestrictiveVisibility", () => {
  const cases: [Visibility, Visibility, Visibility][] = [
    // 同じ同士
    ["public", "public", "public"],
    ["unlisted", "unlisted", "unlisted"],
    ["followers", "followers", "followers"],
    ["direct", "direct", "direct"],
    // public と他
    ["public", "unlisted", "unlisted"],
    ["public", "followers", "followers"],
    ["public", "direct", "direct"],
    // unlisted と他
    ["unlisted", "public", "unlisted"],
    ["unlisted", "followers", "followers"],
    ["unlisted", "direct", "direct"],
    // followers と他
    ["followers", "public", "followers"],
    ["followers", "unlisted", "followers"],
    ["followers", "direct", "direct"],
    // direct と他
    ["direct", "public", "direct"],
    ["direct", "unlisted", "direct"],
    ["direct", "followers", "direct"],
  ];

  it.each(cases)(
    "moreRestrictiveVisibility(%s, %s) === %s",
    (a, b, expected) => {
      expect(moreRestrictiveVisibility(a, b)).toBe(expected);
    },
  );
});

describe("composer store", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  it("defaults to public visibility", async () => {
    const { defaultVisibility } = await import("./composer");
    expect(defaultVisibility()).toBe("public");
  });

  it("defaults rememberVisibility to false", async () => {
    const { rememberVisibility } = await import("./composer");
    expect(rememberVisibility()).toBe(false);
  });

  it("loads saved default visibility from localStorage", async () => {
    localStorage.setItem("defaultVisibility", "unlisted");
    const { defaultVisibility } = await import("./composer");
    expect(defaultVisibility()).toBe("unlisted");
  });

  it("ignores invalid visibility value", async () => {
    localStorage.setItem("defaultVisibility", "invalid");
    const { defaultVisibility } = await import("./composer");
    expect(defaultVisibility()).toBe("public");
  });

  it("loads rememberVisibility from localStorage", async () => {
    localStorage.setItem("rememberVisibility", "true");
    const { rememberVisibility } = await import("./composer");
    expect(rememberVisibility()).toBe(true);
  });

  it("setDefaultVisibility updates signal and localStorage", async () => {
    const { defaultVisibility, setDefaultVisibility } = await import("./composer");
    setDefaultVisibility("followers");
    expect(defaultVisibility()).toBe("followers");
    expect(localStorage.getItem("defaultVisibility")).toBe("followers");
  });

  it("setRememberVisibility updates signal and localStorage", async () => {
    const { rememberVisibility, setRememberVisibility } = await import("./composer");
    setRememberVisibility(true);
    expect(rememberVisibility()).toBe(true);
    expect(localStorage.getItem("rememberVisibility")).toBe("true");
  });

  it("setLastVisibility updates signal and localStorage", async () => {
    const { lastVisibility, setLastVisibility } = await import("./composer");
    setLastVisibility("direct");
    expect(lastVisibility()).toBe("direct");
    expect(localStorage.getItem("lastVisibility")).toBe("direct");
  });

  it("getInitialVisibility returns default when rememberVisibility is false", async () => {
    localStorage.setItem("defaultVisibility", "unlisted");
    localStorage.setItem("lastVisibility", "direct");
    localStorage.setItem("rememberVisibility", "false");
    const { getInitialVisibility } = await import("./composer");
    expect(getInitialVisibility()).toBe("unlisted");
  });

  it("getInitialVisibility returns lastVisibility when rememberVisibility is true", async () => {
    localStorage.setItem("defaultVisibility", "unlisted");
    localStorage.setItem("lastVisibility", "direct");
    localStorage.setItem("rememberVisibility", "true");
    const { getInitialVisibility } = await import("./composer");
    expect(getInitialVisibility()).toBe("direct");
  });
});
