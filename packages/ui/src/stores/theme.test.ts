import { describe, it, expect, beforeEach, vi } from "vitest";

describe("theme store", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  it("defaults to dark theme", async () => {
    const { theme } = await import("./theme");
    expect(theme()).toBe("dark");
  });

  it("defaults to medium font size", async () => {
    const { fontSize } = await import("./theme");
    expect(fontSize()).toBe("medium");
  });

  it("loads saved theme from localStorage", async () => {
    localStorage.setItem("theme", "light");
    const { theme } = await import("./theme");
    expect(theme()).toBe("light");
  });

  it("loads saved font size from localStorage", async () => {
    localStorage.setItem("fontSize", "large");
    const { fontSize } = await import("./theme");
    expect(fontSize()).toBe("large");
  });

  it("ignores invalid theme value", async () => {
    localStorage.setItem("theme", "invalid");
    const { theme } = await import("./theme");
    expect(theme()).toBe("dark");
  });

  it("ignores invalid font size value", async () => {
    localStorage.setItem("fontSize", "invalid");
    const { fontSize } = await import("./theme");
    expect(fontSize()).toBe("medium");
  });

  it("setTheme updates signal and localStorage", async () => {
    const { theme, setTheme } = await import("./theme");
    setTheme("novel");
    expect(theme()).toBe("novel");
    expect(localStorage.getItem("theme")).toBe("novel");
  });

  it("setFontSize updates signal and localStorage", async () => {
    const { fontSize, setFontSize } = await import("./theme");
    setFontSize("xlarge");
    expect(fontSize()).toBe("xlarge");
    expect(localStorage.getItem("fontSize")).toBe("xlarge");
  });

  it("setTheme applies data-theme attribute for non-dark themes", async () => {
    const { setTheme } = await import("./theme");
    setTheme("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("setTheme removes data-theme attribute for dark theme", async () => {
    const { setTheme } = await import("./theme");
    setTheme("light");
    setTheme("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBeNull();
  });

  it("setFontSize applies CSS custom property", async () => {
    const { setFontSize } = await import("./theme");
    setFontSize("large");
    expect(
      document.documentElement.style.getPropertyValue("--font-size-base"),
    ).toBe("20px");
  });

  it("initTheme applies current theme and font size to DOM", async () => {
    localStorage.setItem("theme", "novel");
    localStorage.setItem("fontSize", "small");
    const { initTheme } = await import("./theme");
    initTheme();
    expect(document.documentElement.getAttribute("data-theme")).toBe("novel");
    expect(
      document.documentElement.style.getPropertyValue("--font-size-base"),
    ).toBe("14px");
  });
});
