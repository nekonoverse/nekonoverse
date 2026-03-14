import { describe, it, expect, vi } from "vitest";
import { mentionify } from "./mentionify";

// Mock window.location.hostname
function setHostname(hostname: string) {
  Object.defineProperty(window, "location", {
    value: { hostname },
    writable: true,
    configurable: true,
  });
}

function createMastodonMention(href: string, username: string): HTMLElement {
  // Mastodon format: <a class="u-url mention" href="...">@<span>username</span></a>
  const el = document.createElement("div");
  const a = document.createElement("a");
  a.className = "u-url mention";
  a.href = href;
  a.textContent = "@";
  const span = document.createElement("span");
  span.textContent = username;
  a.appendChild(span);
  el.appendChild(a);
  return el;
}

function createPleromaMention(href: string, username: string): HTMLElement {
  // Pleroma format: <a class="mention" href="...">@username</a>
  const el = document.createElement("div");
  const a = document.createElement("a");
  a.className = "mention";
  a.href = href;
  a.textContent = `@${username}`;
  el.appendChild(a);
  return el;
}

describe("mentionify", () => {
  beforeEach(() => {
    setHostname("local.example.com");
  });

  it("rewrites remote Mastodon mention href to local profile path", () => {
    const el = createMastodonMention("https://remote.example.com/@alice", "alice");

    mentionify(el);

    const link = el.querySelector("a")!;
    expect(link.getAttribute("href")).toBe("/@alice@remote.example.com");
  });

  it("appends domain span for remote Mastodon mention", () => {
    const el = createMastodonMention("https://remote.example.com/@alice", "alice");

    mentionify(el);

    const domain = el.querySelector(".mention-domain");
    expect(domain).not.toBeNull();
    expect(domain!.textContent).toBe("@remote.example.com");
  });

  it("skips local mentions (same hostname)", () => {
    const el = createMastodonMention("https://local.example.com/@bob", "bob");

    mentionify(el);

    const link = el.querySelector("a")!;
    // href should not be modified for local mentions
    expect(link.getAttribute("href")).not.toBe("/@bob@local.example.com");
  });

  it("handles Pleroma/GoToSocial format (no inner span)", () => {
    const el = createPleromaMention("https://pleroma.example.com/users/charlie", "charlie");

    mentionify(el);

    const link = el.querySelector("a")!;
    expect(link.getAttribute("href")).toBe("/@users/charlie@pleroma.example.com");

    const domain = el.querySelector(".mention-domain");
    expect(domain).not.toBeNull();
    expect(domain!.textContent).toBe("@pleroma.example.com");
  });

  it("handles Pleroma format with /@username path", () => {
    const el = createPleromaMention("https://pleroma.example.com/@charlie", "charlie");

    mentionify(el);

    const link = el.querySelector("a")!;
    expect(link.getAttribute("href")).toBe("/@charlie@pleroma.example.com");
  });

  it("handles Mastodon mention with domain already in text", () => {
    const el = document.createElement("div");
    const a = document.createElement("a");
    a.className = "u-url mention";
    a.href = "https://remote.example.com/@alice";
    a.textContent = "@";
    const span = document.createElement("span");
    span.textContent = "alice@remote.example.com";
    a.appendChild(span);
    el.appendChild(a);

    mentionify(el);

    const domain = el.querySelector(".mention-domain");
    expect(domain).not.toBeNull();
    expect(domain!.textContent).toBe("@remote.example.com");
    // Username part should be just "alice"
    const mainSpan = el.querySelector("a span");
    expect(mainSpan!.childNodes[0].textContent).toBe("alice");
  });

  it("attaches click handler for client-side navigation", () => {
    const navigate = vi.fn();
    const el = createMastodonMention("https://remote.example.com/@alice", "alice");

    mentionify(el, navigate);

    const link = el.querySelector("a")!;
    const event = new MouseEvent("click", { bubbles: true, cancelable: true });
    link.dispatchEvent(event);

    expect(navigate).toHaveBeenCalledWith("/@alice@remote.example.com");
  });

  it("does not navigate on ctrl+click", () => {
    const navigate = vi.fn();
    const el = createMastodonMention("https://remote.example.com/@alice", "alice");

    mentionify(el, navigate);

    const link = el.querySelector("a")!;
    const event = new MouseEvent("click", { ctrlKey: true, bubbles: true, cancelable: true });
    link.dispatchEvent(event);

    expect(navigate).not.toHaveBeenCalled();
  });

  it("skips elements with existing .mention-domain", () => {
    const el = createMastodonMention("https://remote.example.com/@alice", "alice");
    const existingDomain = document.createElement("span");
    existingDomain.className = "mention-domain";
    existingDomain.textContent = "@already.set";
    el.querySelector("a span")!.appendChild(existingDomain);

    mentionify(el);

    const domains = el.querySelectorAll(".mention-domain");
    expect(domains.length).toBe(1);
    expect(domains[0].textContent).toBe("@already.set");
  });

  it("skips Mastodon hashtag links (class='mention hashtag')", () => {
    // Mastodon format: <a class="mention hashtag" href="https://remote.example.com/tags/test">#<span>test</span></a>
    const el = document.createElement("div");
    const a = document.createElement("a");
    a.className = "mention hashtag";
    a.href = "https://remote.example.com/tags/test";
    a.textContent = "#";
    const span = document.createElement("span");
    span.textContent = "test";
    a.appendChild(span);
    el.appendChild(a);

    mentionify(el);

    const link = el.querySelector("a")!;
    // href should NOT be rewritten to /@tags/test@remote.example.com
    expect(link.getAttribute("href")).toBe("https://remote.example.com/tags/test");
    // No mention-domain should be added
    expect(el.querySelector(".mention-domain")).toBeNull();
    // Text should remain unchanged
    expect(span.textContent).toBe("test");
  });

  it("processes real mentions but skips hashtags in mixed content", () => {
    const el = document.createElement("div");

    // Real mention
    const mentionA = document.createElement("a");
    mentionA.className = "u-url mention";
    mentionA.href = "https://remote.example.com/@alice";
    mentionA.textContent = "@";
    const mentionSpan = document.createElement("span");
    mentionSpan.textContent = "alice";
    mentionA.appendChild(mentionSpan);
    el.appendChild(mentionA);

    // Hashtag with class="mention hashtag"
    const hashA = document.createElement("a");
    hashA.className = "mention hashtag";
    hashA.href = "https://remote.example.com/tags/nekonoverse";
    hashA.textContent = "#";
    const hashSpan = document.createElement("span");
    hashSpan.textContent = "nekonoverse";
    hashA.appendChild(hashSpan);
    el.appendChild(hashA);

    mentionify(el);

    // Mention should be processed
    expect(mentionA.getAttribute("href")).toBe("/@alice@remote.example.com");
    expect(mentionA.querySelector(".mention-domain")!.textContent).toBe(
      "@remote.example.com",
    );

    // Hashtag should NOT be processed
    expect(hashA.getAttribute("href")).toBe(
      "https://remote.example.com/tags/nekonoverse",
    );
    expect(hashA.querySelector(".mention-domain")).toBeNull();
  });

  it("handles invalid URLs gracefully", () => {
    const el = document.createElement("div");
    const a = document.createElement("a");
    a.className = "mention";
    a.setAttribute("href", "not-a-url");
    a.textContent = "@test";
    el.appendChild(a);

    // Should not throw
    expect(() => mentionify(el)).not.toThrow();
  });
});
