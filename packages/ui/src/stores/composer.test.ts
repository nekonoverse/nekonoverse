import { describe, it, expect, beforeEach, vi } from "vitest";

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
