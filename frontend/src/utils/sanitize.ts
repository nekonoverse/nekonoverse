import DOMPurify from "dompurify";

/**
 * Sanitize HTML string to prevent XSS attacks.
 * Allows safe formatting tags and links only.
 */
export function sanitizeHTML(dirty: string): string {
  return DOMPurify.sanitize(dirty, {
    ALLOWED_TAGS: [
      "a",
      "b",
      "br",
      "em",
      "i",
      "p",
      "span",
      "strong",
      "del",
      "pre",
      "code",
      "blockquote",
      "ul",
      "ol",
      "li",
    ],
    ALLOWED_ATTR: ["href", "rel", "target", "class"],
  });
}
