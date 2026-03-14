import { describe, it, expect } from "vitest";
import { externalLinksNewTab } from "./linkify";

function setOrigin(origin: string) {
  Object.defineProperty(window, "location", {
    value: { origin, hostname: new URL(origin).hostname },
    writable: true,
    configurable: true,
  });
}

function makeEl(html: string): HTMLElement {
  const el = document.createElement("div");
  el.innerHTML = html;
  return el;
}

describe("externalLinksNewTab", () => {
  it("adds target=_blank to external links", () => {
    setOrigin("https://example.com");
    const el = makeEl('<a href="https://other.com">link</a>');
    externalLinksNewTab(el);
    const a = el.querySelector("a")!;
    expect(a.target).toBe("_blank");
    expect(a.rel).toBe("noopener noreferrer");
  });

  it("skips mention links", () => {
    setOrigin("https://example.com");
    const el = makeEl('<a href="https://other.com/@user" class="u-url mention">@user</a>');
    externalLinksNewTab(el);
    const a = el.querySelector("a")!;
    expect(a.target).toBe("");
  });

  it("skips hashtag links", () => {
    setOrigin("https://example.com");
    const el = makeEl('<a href="/tags/test" class="mfm-hashtag">#test</a>');
    externalLinksNewTab(el);
    const a = el.querySelector("a")!;
    expect(a.target).toBe("");
  });

  it("skips relative paths", () => {
    setOrigin("https://example.com");
    const el = makeEl('<a href="/@user">user</a>');
    externalLinksNewTab(el);
    const a = el.querySelector("a")!;
    expect(a.target).toBe("");
  });

  it("skips same-origin links", () => {
    setOrigin("https://example.com");
    const el = makeEl('<a href="https://example.com/about">about</a>');
    externalLinksNewTab(el);
    const a = el.querySelector("a")!;
    expect(a.target).toBe("");
  });

  it("handles multiple links", () => {
    setOrigin("https://example.com");
    const el = makeEl(
      '<a href="https://a.com">a</a> <a href="/@user" class="mention">m</a> <a href="https://b.com">b</a>',
    );
    externalLinksNewTab(el);
    const links = el.querySelectorAll("a");
    expect(links[0].target).toBe("_blank");
    expect(links[1].target).toBe("");
    expect(links[2].target).toBe("_blank");
  });

  it("preserves existing target=_blank", () => {
    setOrigin("https://example.com");
    const el = makeEl('<a href="https://other.com" target="_blank">link</a>');
    externalLinksNewTab(el);
    const a = el.querySelector("a")!;
    expect(a.target).toBe("_blank");
    expect(a.rel).toBe("noopener noreferrer");
  });
});
