import DOMPurify from "dompurify";

const purify = DOMPurify(window);

purify.setConfig({
  ALLOWED_TAGS: [
    "a", "br", "p", "span", "em", "strong", "code", "pre", "blockquote",
  ],
  ALLOWED_ATTR: ["href", "rel", "class", "target"],
});

export function sanitizeHtml(html: string): string {
  return purify.sanitize(html) as string;
}
