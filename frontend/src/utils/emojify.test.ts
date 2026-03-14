import { describe, it, expect } from "vitest";
import { emojify } from "./emojify";
import type { CustomEmoji } from "../api/statuses";

const emoji = (shortcode: string, url: string): CustomEmoji => ({
  shortcode,
  url,
  static_url: url,
});

describe("emojify", () => {
  it("replaces :shortcode: with custom emoji img", () => {
    const el = document.createElement("div");
    el.textContent = "hello :cat: world";
    const emojis = [emoji("cat", "https://example.com/cat.png")];

    emojify(el, emojis);

    const img = el.querySelector("img");
    expect(img).not.toBeNull();
    expect(img!.src).toBe("https://example.com/cat.png");
    expect(img!.alt).toBe(":cat:");
    expect(img!.title).toBe(":cat:");
    expect(img!.className).toBe("custom-emoji");
    expect(img!.draggable).toBe(false);
    expect(el.textContent).toContain("hello");
    expect(el.textContent).toContain("world");
  });

  it("replaces multiple shortcodes", () => {
    const el = document.createElement("div");
    el.textContent = ":cat: and :dog:";
    const emojis = [
      emoji("cat", "https://example.com/cat.png"),
      emoji("dog", "https://example.com/dog.png"),
    ];

    emojify(el, emojis);

    const imgs = el.querySelectorAll("img");
    expect(imgs.length).toBe(2);
    expect(imgs[0].alt).toBe(":cat:");
    expect(imgs[1].alt).toBe(":dog:");
  });

  it("leaves unknown shortcodes as text", () => {
    const el = document.createElement("div");
    el.textContent = ":unknown: stays";
    const emojis = [emoji("cat", "https://example.com/cat.png")];

    emojify(el, emojis);

    expect(el.querySelectorAll("img").length).toBe(0);
    expect(el.textContent).toBe(":unknown: stays");
  });

  it("does nothing with empty emoji list", () => {
    const el = document.createElement("div");
    el.textContent = ":cat: test";

    emojify(el, []);

    expect(el.querySelectorAll("img").length).toBe(0);
    expect(el.textContent).toBe(":cat: test");
  });

  it("does nothing with null/undefined emoji list", () => {
    const el = document.createElement("div");
    el.textContent = ":cat: test";

    emojify(el, null as any);

    expect(el.textContent).toBe(":cat: test");
  });

  it("handles shortcode at start and end of text", () => {
    const el = document.createElement("div");
    el.textContent = ":cat:";
    const emojis = [emoji("cat", "https://example.com/cat.png")];

    emojify(el, emojis);

    const img = el.querySelector("img");
    expect(img).not.toBeNull();
    expect(img!.alt).toBe(":cat:");
  });

  it("handles consecutive shortcodes", () => {
    const el = document.createElement("div");
    el.textContent = ":cat::dog:";
    const emojis = [
      emoji("cat", "https://example.com/cat.png"),
      emoji("dog", "https://example.com/dog.png"),
    ];

    emojify(el, emojis);

    const imgs = el.querySelectorAll("img");
    expect(imgs.length).toBe(2);
  });

  it("preserves surrounding HTML structure", () => {
    const el = document.createElement("div");
    const span = document.createElement("span");
    span.textContent = "in span :cat: here";
    el.appendChild(span);
    const emojis = [emoji("cat", "https://example.com/cat.png")];

    emojify(el, emojis);

    expect(span.querySelector("img")).not.toBeNull();
  });

  it("handles shortcodes with underscores and numbers", () => {
    const el = document.createElement("div");
    el.textContent = ":blobcat_3:";
    const emojis = [emoji("blobcat_3", "https://example.com/blobcat3.png")];

    emojify(el, emojis);

    const img = el.querySelector("img");
    expect(img).not.toBeNull();
    expect(img!.alt).toBe(":blobcat_3:");
  });
});
