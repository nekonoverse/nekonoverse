import { describe, it, expect } from "vitest";
import { renderMfm, isSafeUrl } from "./mfm";
import type { CustomEmoji } from "../api/statuses";

const emoji = (shortcode: string, url: string): CustomEmoji => ({
  shortcode,
  url,
  static_url: url,
});

describe("isSafeUrl", () => {
  it("allows http URLs", () => {
    expect(isSafeUrl("http://example.com")).toBe(true);
  });

  it("allows https URLs", () => {
    expect(isSafeUrl("https://example.com/path")).toBe(true);
  });

  it("blocks javascript: URLs", () => {
    expect(isSafeUrl("javascript:alert(1)")).toBe(false);
  });

  it("blocks data: URLs", () => {
    expect(isSafeUrl("data:text/html,<script>alert(1)</script>")).toBe(false);
  });

  it("blocks vbscript: URLs", () => {
    expect(isSafeUrl("vbscript:msgbox")).toBe(false);
  });

  it("handles empty string (resolved against https base)", () => {
    // Empty string resolves against the https:// dummy base, so it's technically safe
    expect(isSafeUrl("")).toBe(true);
  });

  it("blocks ftp: protocol", () => {
    expect(isSafeUrl("ftp://example.com/file")).toBe(false);
  });

  it("handles relative URLs as safe (resolved against https base)", () => {
    expect(isSafeUrl("/path/to/page")).toBe(true);
  });
});

describe("renderMfm", () => {
  it("renders plain text", () => {
    const el = document.createElement("div");
    renderMfm(el, "hello world", []);
    expect(el.textContent).toBe("hello world");
  });

  it("renders bold text", () => {
    const el = document.createElement("div");
    renderMfm(el, "**bold**", []);
    const strong = el.querySelector("strong");
    expect(strong).not.toBeNull();
    expect(strong!.textContent).toBe("bold");
  });

  it("renders italic text", () => {
    const el = document.createElement("div");
    renderMfm(el, "<i>italic</i>", []);
    const em = el.querySelector("em");
    expect(em).not.toBeNull();
    expect(em!.textContent).toBe("italic");
  });

  it("renders strikethrough text", () => {
    const el = document.createElement("div");
    renderMfm(el, "~~strike~~", []);
    const del = el.querySelector("del");
    expect(del).not.toBeNull();
    expect(del!.textContent).toBe("strike");
  });

  it("renders inline code", () => {
    const el = document.createElement("div");
    renderMfm(el, "`code`", []);
    const code = el.querySelector("code.mfm-inline-code");
    expect(code).not.toBeNull();
    expect(code!.textContent).toBe("code");
  });

  it("renders code blocks", () => {
    const el = document.createElement("div");
    renderMfm(el, "```js\nconsole.log(1)\n```", []);
    const pre = el.querySelector("pre.mfm-code-block");
    expect(pre).not.toBeNull();
    const code = pre!.querySelector("code");
    expect(code).not.toBeNull();
    expect(code!.getAttribute("data-lang")).toBe("js");
    expect(code!.textContent).toBe("console.log(1)");
  });

  it("renders custom emoji", () => {
    const el = document.createElement("div");
    const emojis = [emoji("cat", "https://example.com/cat.png")];
    renderMfm(el, ":cat:", emojis);
    const img = el.querySelector("img.custom-emoji");
    expect(img).not.toBeNull();
    expect(img!.getAttribute("src")).toBe("https://example.com/cat.png");
    expect(img!.getAttribute("alt")).toBe(":cat:");
  });

  it("renders unknown custom emoji as text", () => {
    const el = document.createElement("div");
    renderMfm(el, ":unknown:", []);
    expect(el.textContent).toBe(":unknown:");
    expect(el.querySelector("img")).toBeNull();
  });

  it("renders URLs as links", () => {
    const el = document.createElement("div");
    renderMfm(el, "https://example.com", []);
    const link = el.querySelector("a");
    expect(link).not.toBeNull();
    expect(link!.href).toBe("https://example.com/");
    expect(link!.target).toBe("_blank");
    expect(link!.rel).toContain("nofollow");
  });

  it("renders unsafe URLs as plain text", () => {
    const el = document.createElement("div");
    renderMfm(el, "[click](javascript:alert(1))", []);
    const link = el.querySelector("a");
    // Should not have an anchor with javascript: href
    if (link) {
      expect(link.href).not.toContain("javascript:");
    }
  });

  it("renders mentions with local link", () => {
    const el = document.createElement("div");
    renderMfm(el, "@alice@remote.example.com", []);
    const link = el.querySelector("a.mention");
    expect(link).not.toBeNull();
    expect(link!.getAttribute("href")).toBe("/@alice@remote.example.com");
    const domain = link!.querySelector(".mention-domain");
    expect(domain).not.toBeNull();
    expect(domain!.textContent).toBe("@remote.example.com");
  });

  it("renders local mentions without domain", () => {
    const el = document.createElement("div");
    renderMfm(el, "@alice", []);
    const link = el.querySelector("a.mention");
    expect(link).not.toBeNull();
    expect(link!.getAttribute("href")).toBe("/@alice");
  });

  it("renders hashtags", () => {
    const el = document.createElement("div");
    renderMfm(el, "#test", []);
    const link = el.querySelector("a.mfm-hashtag");
    expect(link).not.toBeNull();
    expect(link!.textContent).toBe("#test");
    expect(link!.getAttribute("href")).toBe("/tags/test");
  });

  it("renders quote blocks", () => {
    const el = document.createElement("div");
    renderMfm(el, "> quoted text", []);
    const blockquote = el.querySelector("blockquote.mfm-quote");
    expect(blockquote).not.toBeNull();
    expect(blockquote!.textContent).toContain("quoted text");
  });

  it("renders center blocks", () => {
    const el = document.createElement("div");
    renderMfm(el, "<center>centered</center>", []);
    const div = el.querySelector("div.mfm-center");
    expect(div).not.toBeNull();
    expect(div!.textContent).toBe("centered");
  });

  it("renders newlines as br tags", () => {
    const el = document.createElement("div");
    renderMfm(el, "line1\nline2", []);
    const br = el.querySelector("br");
    expect(br).not.toBeNull();
  });

  it("renders unicode emoji as twemoji", () => {
    const el = document.createElement("div");
    renderMfm(el, "\u{1f600}", []);
    const img = el.querySelector("img.twemoji");
    expect(img).not.toBeNull();
    expect(img!.getAttribute("alt")).toBe("\u{1f600}");
  });

  describe("MFM functions ($[...])", () => {
    it("renders $[x2 ...] with doubled font size", () => {
      const el = document.createElement("div");
      renderMfm(el, "$[x2 big]", []);
      const span = el.querySelector(".mfm-fn") as HTMLElement;
      expect(span).not.toBeNull();
      expect(span!.style.fontSize).toBe("200%");
    });

    it("renders $[flip ...] with scaleX transform", () => {
      const el = document.createElement("div");
      renderMfm(el, "$[flip flipped]", []);
      const span = el.querySelector(".mfm-fn") as HTMLElement;
      expect(span).not.toBeNull();
      expect(span!.style.transform).toBe("scaleX(-1)");
    });

    it("renders $[flip.v ...] with scaleY transform", () => {
      const el = document.createElement("div");
      renderMfm(el, "$[flip.v flipped]", []);
      const span = el.querySelector(".mfm-fn") as HTMLElement;
      expect(span).not.toBeNull();
      expect(span!.style.transform).toBe("scaleY(-1)");
    });

    it("renders $[flip.h,v ...] with both axes flipped", () => {
      const el = document.createElement("div");
      renderMfm(el, "$[flip.h,v flipped]", []);
      const span = el.querySelector(".mfm-fn") as HTMLElement;
      expect(span).not.toBeNull();
      expect(span!.style.transform).toBe("scale(-1, -1)");
    });

    it("renders $[fg.color=ff0000 ...] with text color", () => {
      const el = document.createElement("div");
      renderMfm(el, "$[fg.color=ff0000 red text]", []);
      const span = el.querySelector(".mfm-fn") as HTMLElement;
      expect(span).not.toBeNull();
      // jsdom may normalize to rgb()
      expect(span!.style.color).toBeTruthy();
    });

    it("rejects invalid hex color in $[fg ...]", () => {
      const el = document.createElement("div");
      renderMfm(el, "$[fg.color=xyz invalid]", []);
      const span = el.querySelector(".mfm-fn") as HTMLElement;
      expect(span!.style.color).toBe("");
    });

    it("renders $[bg.color=00ff00 ...] with background color", () => {
      const el = document.createElement("div");
      renderMfm(el, "$[bg.color=00ff00 green bg]", []);
      const span = el.querySelector(".mfm-fn") as HTMLElement;
      expect(span).not.toBeNull();
      // jsdom may normalize to rgb()
      expect(span!.style.backgroundColor).toBeTruthy();
    });

    it("renders $[font.monospace ...]", () => {
      const el = document.createElement("div");
      renderMfm(el, "$[font.monospace mono]", []);
      const span = el.querySelector(".mfm-fn") as HTMLElement;
      expect(span).not.toBeNull();
      expect(span!.style.fontFamily).toBe("monospace");
    });

    it("rejects unsafe font names", () => {
      const el = document.createElement("div");
      renderMfm(el, "$[font.arial text]", []);
      const span = el.querySelector(".mfm-fn") as HTMLElement;
      expect(span!.style.fontFamily).toBe("");
    });

    it("renders $[blur ...] with blur class", () => {
      const el = document.createElement("div");
      renderMfm(el, "$[blur blurred]", []);
      const span = el.querySelector(".mfm-fn-blur");
      expect(span).not.toBeNull();
    });

    it("renders $[rotate.deg=45 ...]", () => {
      const el = document.createElement("div");
      renderMfm(el, "$[rotate.deg=45 rotated]", []);
      const span = el.querySelector(".mfm-fn") as HTMLElement;
      expect(span).not.toBeNull();
      expect(span!.style.transform).toBe("rotate(45deg)");
    });

    it("renders $[border ...] with validated styles", () => {
      const el = document.createElement("div");
      renderMfm(el, "$[border.style=dashed,width=2,color=ff0000 bordered]", []);
      const span = el.querySelector(".mfm-fn") as HTMLElement;
      expect(span).not.toBeNull();
      expect(span!.style.border).toContain("dashed");
      expect(span!.style.border).toContain("2px");
    });

    it("rejects unsafe border style values", () => {
      const el = document.createElement("div");
      // Use a single-word unsafe value (no parens which confuse mfm-js parser)
      renderMfm(el, "$[border.style=inherit bordered]", []);
      const span = el.querySelector(".mfm-fn") as HTMLElement;
      expect(span).not.toBeNull();
      // "inherit" is not in SAFE_BORDER_STYLES, should fall back to "solid"
      expect(span!.style.border).toContain("solid");
    });

    it("validates speed as CSS duration", () => {
      const el = document.createElement("div");
      renderMfm(el, "$[tada.speed=2s tada]", []);
      const span = el.querySelector(".mfm-fn-tada") as HTMLElement;
      expect(span).not.toBeNull();
      expect(span!.style.getPropertyValue("--mfm-speed")).toBe("2s");
    });

    it("rejects invalid speed values", () => {
      const el = document.createElement("div");
      renderMfm(el, "$[tada.speed=invalid tada]", []);
      const span = el.querySelector(".mfm-fn-tada") as HTMLElement;
      expect(span).not.toBeNull();
      expect(span!.style.getPropertyValue("--mfm-speed")).toBe("");
    });

    it("renders $[scale ...] with clamped values", () => {
      const el = document.createElement("div");
      renderMfm(el, "$[scale.x=10,y=10 huge]", []);
      const span = el.querySelector(".mfm-fn") as HTMLElement;
      // Scale should be clamped to [-5, 5]
      expect(span!.style.transform).toBe("scale(5, 5)");
    });

    it("renders $[sparkle ...] with sparkle class", () => {
      const el = document.createElement("div");
      renderMfm(el, "$[sparkle sparkling]", []);
      const span = el.querySelector(".mfm-fn-sparkle");
      expect(span).not.toBeNull();
    });

    it("renders animation functions with class", () => {
      for (const fn of ["tada", "jelly", "twitch", "shake", "jump", "bounce", "rainbow"]) {
        const el = document.createElement("div");
        renderMfm(el, `$[${fn} text]`, []);
        const span = el.querySelector(`.mfm-fn-${fn}`);
        expect(span, `$[${fn}] should have class mfm-fn-${fn}`).not.toBeNull();
      }
    });
  });

  it("attaches click handler to mentions for navigation", () => {
    const navigate = vi.fn();
    const el = document.createElement("div");
    renderMfm(el, "@alice", [], navigate);

    const link = el.querySelector("a.mention") as HTMLAnchorElement;
    expect(link).not.toBeNull();

    const event = new MouseEvent("click", { bubbles: true, cancelable: true });
    link.dispatchEvent(event);
    expect(navigate).toHaveBeenCalledWith("/@alice");
  });

  it("attaches click handler to hashtags for navigation", () => {
    const navigate = vi.fn();
    const el = document.createElement("div");
    renderMfm(el, "#solidjs", [], navigate);

    const link = el.querySelector("a.mfm-hashtag") as HTMLAnchorElement;
    expect(link).not.toBeNull();

    const event = new MouseEvent("click", { bubbles: true, cancelable: true });
    link.dispatchEvent(event);
    expect(navigate).toHaveBeenCalledWith("/tags/solidjs");
  });

  it("supplements actorHost for hostless mentions", () => {
    const el = document.createElement("div");
    renderMfm(el, "@alice", [], undefined, "remote.example.com");
    const link = el.querySelector("a.mention");
    expect(link!.getAttribute("href")).toBe("/@alice@remote.example.com");
  });

  it("clears existing content before rendering", () => {
    const el = document.createElement("div");
    el.textContent = "old content";
    renderMfm(el, "new content", []);
    expect(el.textContent).toBe("new content");
  });
});
