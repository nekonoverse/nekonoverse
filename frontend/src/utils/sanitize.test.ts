import { describe, it, expect } from "vitest";
import { sanitizeHtml } from "./sanitize";

describe("sanitizeHtml", () => {
  it("allows safe tags", () => {
    const html = '<p>Hello <strong>world</strong></p>';
    expect(sanitizeHtml(html)).toBe('<p>Hello <strong>world</strong></p>');
  });

  it("allows br tags", () => {
    const html = "line1<br>line2";
    expect(sanitizeHtml(html)).toContain("line1");
    expect(sanitizeHtml(html)).toContain("line2");
    expect(sanitizeHtml(html)).toContain("<br>");
  });

  it("allows em, code, pre, blockquote, span tags", () => {
    const html = '<em>italic</em><code>code</code><pre>preformatted</pre><blockquote>quote</blockquote><span>span</span>';
    const result = sanitizeHtml(html);
    expect(result).toContain("<em>");
    expect(result).toContain("<code>");
    expect(result).toContain("<pre>");
    expect(result).toContain("<blockquote>");
    expect(result).toContain("<span>");
  });

  it("strips script tags", () => {
    const html = '<p>Safe</p><script>alert("xss")</script>';
    const result = sanitizeHtml(html);
    expect(result).not.toContain("<script>");
    expect(result).not.toContain("alert");
    expect(result).toContain("Safe");
  });

  it("strips onclick handlers", () => {
    const html = '<p onclick="alert(1)">Click</p>';
    const result = sanitizeHtml(html);
    expect(result).not.toContain("onclick");
    expect(result).toContain("Click");
  });

  it("preserves href on anchor tags", () => {
    const html = '<a href="https://example.com" rel="nofollow">Link</a>';
    const result = sanitizeHtml(html);
    expect(result).toContain('href="https://example.com"');
    expect(result).toContain("Link");
  });

  it("strips disallowed tags like img, div, iframe", () => {
    const html = '<div>text</div><img src="x"><iframe src="x"></iframe>';
    const result = sanitizeHtml(html);
    expect(result).not.toContain("<div");
    expect(result).not.toContain("<img");
    expect(result).not.toContain("<iframe");
    expect(result).toContain("text");
  });

  it("strips style attribute", () => {
    const html = '<p style="color:red">Styled</p>';
    const result = sanitizeHtml(html);
    expect(result).not.toContain("style");
    expect(result).toContain("Styled");
  });

  it("handles empty string", () => {
    expect(sanitizeHtml("")).toBe("");
  });

  it("handles plain text", () => {
    expect(sanitizeHtml("Hello world")).toBe("Hello world");
  });
});
