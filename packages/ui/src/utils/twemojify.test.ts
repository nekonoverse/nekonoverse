import { describe, it, expect } from "vitest";
import { twemojify } from "./twemojify";

describe("twemojify", () => {
  it("replaces Unicode emoji with twemoji img", () => {
    const el = document.createElement("div");
    el.textContent = "hello \u{1f600} world";

    twemojify(el);

    const img = el.querySelector("img");
    expect(img).not.toBeNull();
    expect(img!.className).toBe("twemoji");
    expect(img!.alt).toBe("\u{1f600}");
    expect(img!.draggable).toBe(false);
    expect(img!.src).toContain("1f600.svg");
  });

  it("preserves surrounding text", () => {
    const el = document.createElement("div");
    el.textContent = "before \u{1f600} after";

    twemojify(el);

    expect(el.textContent).toContain("before");
    expect(el.textContent).toContain("after");
  });

  it("replaces multiple emojis", () => {
    const el = document.createElement("div");
    el.textContent = "\u{1f600}\u{1f601}";

    twemojify(el);

    const imgs = el.querySelectorAll("img");
    expect(imgs.length).toBe(2);
  });

  it("does nothing when no emoji present", () => {
    const el = document.createElement("div");
    el.textContent = "just plain text";

    twemojify(el);

    expect(el.querySelectorAll("img").length).toBe(0);
    expect(el.textContent).toBe("just plain text");
  });

  it("handles emoji in nested elements", () => {
    const el = document.createElement("div");
    const span = document.createElement("span");
    span.textContent = "nested \u{1f600}";
    el.appendChild(span);

    twemojify(el);

    expect(span.querySelector("img")).not.toBeNull();
  });

  it("handles emoji with variation selector", () => {
    const el = document.createElement("div");
    // Red heart with variation selector: U+2764 U+FE0F
    el.textContent = "\u2764\uFE0F";

    twemojify(el);

    const img = el.querySelector("img");
    expect(img).not.toBeNull();
    expect(img!.className).toBe("twemoji");
  });
});
