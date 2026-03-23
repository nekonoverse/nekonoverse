import katex from "katex";
import * as mfm from "mfm-js";
import type { MfmNode } from "mfm-js";
import type { CustomEmoji } from "../types/emoji";
import { emojiToUrl } from "./twemoji";

const HEX_COLOR_RE = /^[0-9a-fA-F]{3,6}$/;
const SAFE_FONTS = new Set(["serif", "monospace", "cursive", "fantasy", "math"]);
const SAFE_URL_PROTOCOLS = new Set(["http:", "https:"]);
const SAFE_BORDER_STYLES = new Set([
  "solid", "dashed", "dotted", "double", "groove", "ridge", "inset", "outset", "none",
]);
const NUMERIC_RE = /^\d+(\.\d+)?$/;
const CSS_DURATION_RE = /^\d+(\.\d+)?(s|ms)$/;

/**
 * Check whether a URL uses a safe protocol (http/https only).
 * Blocks javascript:, data:, vbscript:, and all other non-http protocols
 * to prevent XSS from malicious remote MFM content.
 */
export function isSafeUrl(url: string): boolean {
  try {
    const parsed = new URL(url, "https://dummy.invalid");
    return SAFE_URL_PROTOCOLS.has(parsed.protocol);
  } catch {
    return false;
  }
}

/**
 * Parse MFM source text and render it as DOM nodes into the target element.
 * All DOM nodes are created programmatically — no innerHTML, no XSS risk.
 */
export function renderMfm(
  el: HTMLElement,
  source: string,
  emojis: CustomEmoji[],
  navigate?: (path: string) => void,
  actorHost?: string | null,
): void {
  el.textContent = "";

  const ast = mfm.parse(source);
  const emojiMap = new Map<string, CustomEmoji>();
  for (const emoji of emojis) {
    emojiMap.set(emoji.shortcode, emoji);
  }

  for (const node of ast) {
    el.appendChild(renderNode(node, emojiMap, navigate, actorHost));
  }
}

function renderChildren(
  parent: HTMLElement,
  children: MfmNode[],
  emojiMap: Map<string, CustomEmoji>,
  navigate?: (path: string) => void,
  actorHost?: string | null,
): void {
  for (const child of children) {
    parent.appendChild(renderNode(child, emojiMap, navigate, actorHost));
  }
}

function renderNode(
  node: MfmNode,
  emojiMap: Map<string, CustomEmoji>,
  navigate?: (path: string) => void,
  actorHost?: string | null,
): Node {
  switch (node.type) {
    case "text": {
      const frag = document.createDocumentFragment();
      const lines = node.props.text.split("\n");
      for (let i = 0; i < lines.length; i++) {
        if (i > 0) frag.appendChild(document.createElement("br"));
        if (lines[i]) frag.appendChild(document.createTextNode(lines[i]));
      }
      return frag;
    }

    case "bold": {
      const el = document.createElement("strong");
      renderChildren(el, node.children, emojiMap, navigate, actorHost);
      return el;
    }

    case "italic": {
      const el = document.createElement("em");
      renderChildren(el, node.children, emojiMap, navigate, actorHost);
      return el;
    }

    case "strike": {
      const el = document.createElement("del");
      renderChildren(el, node.children, emojiMap, navigate, actorHost);
      return el;
    }

    case "small": {
      const el = document.createElement("small");
      el.className = "mfm-small";
      renderChildren(el, node.children, emojiMap, navigate, actorHost);
      return el;
    }

    case "center": {
      const el = document.createElement("div");
      el.className = "mfm-center";
      renderChildren(el, node.children, emojiMap, navigate, actorHost);
      return el;
    }

    case "quote": {
      const el = document.createElement("blockquote");
      el.className = "mfm-quote";
      renderChildren(el, node.children, emojiMap, navigate, actorHost);
      return el;
    }

    case "inlineCode": {
      const el = document.createElement("code");
      el.className = "mfm-inline-code";
      el.textContent = node.props.code;
      return el;
    }

    case "blockCode": {
      const pre = document.createElement("pre");
      pre.className = "mfm-code-block";
      const code = document.createElement("code");
      code.textContent = node.props.code;
      if (node.props.lang) code.setAttribute("data-lang", node.props.lang);
      pre.appendChild(code);
      return pre;
    }

    case "mathInline": {
      if (localStorage.getItem("nekonoverse:katex-render") === "false") {
        const el = document.createElement("code");
        el.className = "mfm-math-inline";
        el.textContent = node.props.formula;
        return el;
      }
      const el = document.createElement("span");
      el.className = "mfm-math-inline";
      try {
        katex.render(node.props.formula, el, { throwOnError: false, displayMode: false });
      } catch {
        el.textContent = node.props.formula;
      }
      return el;
    }

    case "mathBlock": {
      if (localStorage.getItem("nekonoverse:katex-render") === "false") {
        const pre = document.createElement("pre");
        pre.className = "mfm-math-block";
        const code = document.createElement("code");
        code.textContent = node.props.formula;
        pre.appendChild(code);
        return pre;
      }
      const el = document.createElement("div");
      el.className = "mfm-math-block";
      try {
        katex.render(node.props.formula, el, { throwOnError: false, displayMode: true });
      } catch {
        el.textContent = node.props.formula;
      }
      return el;
    }

    case "link": {
      if (!isSafeUrl(node.props.url)) {
        // Unsafe protocol — render children as plain text
        const span = document.createElement("span");
        renderChildren(span, node.children, emojiMap, navigate, actorHost);
        return span;
      }
      const el = document.createElement("a");
      el.href = node.props.url;
      el.target = "_blank";
      el.rel = "nofollow noopener noreferrer";
      renderChildren(el, node.children, emojiMap, navigate, actorHost);
      return el;
    }

    case "url": {
      if (!isSafeUrl(node.props.url)) {
        // Unsafe protocol — render as plain text
        return document.createTextNode(node.props.url);
      }
      const el = document.createElement("a");
      el.href = node.props.url;
      el.target = "_blank";
      el.rel = "nofollow noopener noreferrer";
      el.textContent = node.props.url;
      return el;
    }

    case "mention": {
      const el = document.createElement("a");
      el.className = "u-url mention";
      const { username } = node.props;
      // host がない場合、リモートノートならノート作者のドメインを補完
      const host = node.props.host || (actorHost ? actorHost : null);
      const localPath = host ? `/@${username}@${host}` : `/@${username}`;
      el.href = localPath;

      const span = document.createElement("span");
      span.className = "h-card";
      const inner = document.createElement("span");
      inner.textContent = `@${username}`;
      span.appendChild(inner);
      if (host) {
        const domainSpan = document.createElement("span");
        domainSpan.className = "mention-domain";
        domainSpan.textContent = `@${host}`;
        span.appendChild(domainSpan);
      }
      el.appendChild(span);

      if (navigate) {
        el.addEventListener("click", (e) => {
          if (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
          e.preventDefault();
          navigate(localPath);
        });
      }
      return el;
    }

    case "hashtag": {
      const el = document.createElement("a");
      el.className = "mfm-hashtag";
      el.href = `/tags/${node.props.hashtag}`;
      el.textContent = `#${node.props.hashtag}`;
      if (navigate) {
        el.addEventListener("click", (e) => {
          if (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
          e.preventDefault();
          navigate(`/tags/${node.props.hashtag}`);
        });
      }
      return el;
    }

    case "emojiCode": {
      const emoji = emojiMap.get(node.props.name);
      if (emoji) {
        const img = document.createElement("img");
        img.className = "custom-emoji";
        img.src = emoji.url;
        img.alt = `:${node.props.name}:`;
        img.title = `:${node.props.name}:`;
        img.draggable = false;
        return img;
      }
      return document.createTextNode(`:${node.props.name}:`);
    }

    case "unicodeEmoji": {
      const img = document.createElement("img");
      img.className = "twemoji";
      img.src = emojiToUrl(node.props.emoji);
      img.alt = node.props.emoji;
      img.draggable = false;
      return img;
    }

    case "search": {
      const div = document.createElement("div");
      div.className = "mfm-search";
      const input = document.createElement("span");
      input.textContent = node.props.query;
      div.appendChild(input);
      return div;
    }

    case "plain": {
      const frag = document.createDocumentFragment();
      for (const child of node.children) {
        if (child.type === "text") {
          const lines = child.props.text.split("\n");
          for (let i = 0; i < lines.length; i++) {
            if (i > 0) frag.appendChild(document.createElement("br"));
            if (lines[i]) frag.appendChild(document.createTextNode(lines[i]));
          }
        }
      }
      return frag;
    }

    case "fn": {
      return renderFn(node, emojiMap, navigate, actorHost);
    }

    default: {
      // Unknown node type: render children if they exist
      const frag = document.createDocumentFragment();
      if ("children" in node && Array.isArray((node as any).children)) {
        for (const child of (node as any).children) {
          frag.appendChild(renderNode(child, emojiMap, navigate, actorHost));
        }
      }
      return frag;
    }
  }
}

function renderFn(
  node: MfmNode & { type: "fn" },
  emojiMap: Map<string, CustomEmoji>,
  navigate?: (path: string) => void,
  actorHost?: string | null,
): Node {
  const { name, args } = node.props;
  const el = document.createElement("span");
  el.classList.add("mfm-fn");

  // Speed custom property (validate as CSS duration)
  if (typeof args.speed === "string" && CSS_DURATION_RE.test(args.speed)) {
    el.style.setProperty("--mfm-speed", args.speed);
  }

  switch (name) {
    case "tada":
    case "jelly":
    case "twitch":
    case "shake":
    case "jump":
    case "bounce":
    case "rainbow":
      el.classList.add(`mfm-fn-${name}`);
      break;

    case "spin": {
      el.classList.add("mfm-fn-spin");
      if (args.left === true) el.classList.add("mfm-spin-left");
      if (args.alternate === true) el.classList.add("mfm-spin-alternate");
      if (args.x === true) el.classList.add("mfm-spin-x");
      if (args.y === true) el.classList.add("mfm-spin-y");
      break;
    }

    case "flip": {
      const h = args.h === true;
      const v = args.v === true;
      if (h && v) {
        el.style.transform = "scale(-1, -1)";
      } else if (v) {
        el.style.transform = "scaleY(-1)";
      } else {
        el.style.transform = "scaleX(-1)";
      }
      break;
    }

    case "x2":
      el.style.fontSize = "200%";
      break;
    case "x3":
      el.style.fontSize = "300%";
      break;
    case "x4":
      el.style.fontSize = "400%";
      break;

    case "font": {
      const family = Object.keys(args).find((k) => SAFE_FONTS.has(k));
      if (family) el.style.fontFamily = family;
      break;
    }

    case "blur":
      el.classList.add("mfm-fn-blur");
      break;

    case "rotate": {
      const deg = typeof args.deg === "string" ? parseFloat(args.deg) : 90;
      if (!isNaN(deg)) el.style.transform = `rotate(${deg}deg)`;
      break;
    }

    case "position": {
      const x = typeof args.x === "string" ? parseFloat(args.x) : 0;
      const y = typeof args.y === "string" ? parseFloat(args.y) : 0;
      if (!isNaN(x) && !isNaN(y)) {
        el.style.transform = `translate(${x}em, ${y}em)`;
      }
      break;
    }

    case "scale": {
      let sx = typeof args.x === "string" ? parseFloat(args.x) : 1;
      let sy = typeof args.y === "string" ? parseFloat(args.y) : 1;
      sx = Math.min(Math.max(sx, -5), 5);
      sy = Math.min(Math.max(sy, -5), 5);
      el.style.transform = `scale(${sx}, ${sy})`;
      break;
    }

    case "fg": {
      const color = typeof args.color === "string" ? args.color : null;
      if (color && HEX_COLOR_RE.test(color)) {
        el.style.color = `#${color}`;
      }
      break;
    }

    case "bg": {
      const color = typeof args.color === "string" ? args.color : null;
      if (color && HEX_COLOR_RE.test(color)) {
        el.style.backgroundColor = `#${color}`;
      }
      break;
    }

    case "border": {
      const rawStyle = typeof args.style === "string" ? args.style : "solid";
      const style = SAFE_BORDER_STYLES.has(rawStyle) ? rawStyle : "solid";
      const rawWidth = typeof args.width === "string" ? args.width : "1";
      const width = NUMERIC_RE.test(rawWidth) ? rawWidth : "1";
      const rawRadius = typeof args.radius === "string" ? args.radius : "0";
      const radius = NUMERIC_RE.test(rawRadius) ? rawRadius : "0";
      const color = typeof args.color === "string" && HEX_COLOR_RE.test(args.color)
        ? `#${args.color}`
        : "var(--border)";
      el.style.border = `${width}px ${style} ${color}`;
      if (radius !== "0") el.style.borderRadius = `${radius}px`;
      el.style.padding = "0.2em";
      break;
    }

    case "ruby": {
      const ruby = document.createElement("ruby");
      renderChildren(ruby, node.children, emojiMap, navigate, actorHost);
      // mfm-js parses ruby as $[ruby text reading] where last child text is the reading
      const texts = ruby.textContent?.split(" ") ?? [];
      if (texts.length >= 2) {
        const reading = texts.pop()!;
        ruby.textContent = "";
        ruby.appendChild(document.createTextNode(texts.join(" ")));
        const rt = document.createElement("rt");
        rt.textContent = reading;
        ruby.appendChild(rt);
      }
      return ruby;
    }

    case "sparkle":
      el.classList.add("mfm-fn-sparkle");
      break;

    default:
      // Unknown fn: just render children
      break;
  }

  if (name !== "ruby") {
    renderChildren(el, node.children, emojiMap, navigate, actorHost);
  }

  return el;
}
