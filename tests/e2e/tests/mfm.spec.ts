import { test, expect, type Page } from "@playwright/test";
import { loginAsAdmin, createNote } from "./helpers";

/**
 * Find a .note-content element inside the note-card that contains the given text.
 * Using filter({ hasText }) instead of .first() prevents picking up notes from
 * other tests when running sharded in CI.
 */
function findNoteContent(page: Page, text: string) {
  return page
    .locator(".note-card")
    .filter({ hasText: text })
    .first()
    .locator(".note-content");
}

test.describe("MFM Rendering", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("bold, italic, and strikethrough render correctly", async ({ page }) => {
    await createNote(page, "**bold text** *italic text* ~~strike text~~");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = findNoteContent(page, "bold text");
    await expect(noteContent.locator("strong")).toContainText("bold text", { timeout: 10_000 });
    await expect(noteContent.locator("em")).toContainText("italic text");
    await expect(noteContent.locator("del")).toContainText("strike text");
  });

  test("inline code renders correctly", async ({ page }) => {
    await createNote(page, "here is `some code` inline");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = findNoteContent(page, "some code");
    const code = noteContent.locator("code.mfm-inline-code");
    await expect(code).toBeVisible({ timeout: 10_000 });
    await expect(code).toContainText("some code");
  });

  test("code block renders correctly", async ({ page }) => {
    await createNote(page, "```js\nconsole.log('hello');\n```");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = findNoteContent(page, "console.log");
    const codeBlock = noteContent.locator("pre.mfm-code-block code");
    await expect(codeBlock).toBeVisible({ timeout: 10_000 });
    await expect(codeBlock).toContainText("console.log");
  });

  test("MFM shake function produces animated element", async ({ page }) => {
    await createNote(page, "$[shake shaking text]");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = findNoteContent(page, "shaking text");
    const shakeEl = noteContent.locator(".mfm-fn-shake");
    await expect(shakeEl).toBeVisible({ timeout: 10_000 });
    await expect(shakeEl).toContainText("shaking text");
  });

  test("MFM spin function produces animated element", async ({ page }) => {
    await createNote(page, "$[spin spinning text]");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = findNoteContent(page, "spinning text");
    const spinEl = noteContent.locator(".mfm-fn-spin");
    await expect(spinEl).toBeVisible({ timeout: 10_000 });
    await expect(spinEl).toContainText("spinning text");
  });

  test("MFM bounce function produces animated element", async ({ page }) => {
    await createNote(page, "$[bounce bouncing text]");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = findNoteContent(page, "bouncing text");
    const bounceEl = noteContent.locator(".mfm-fn-bounce");
    await expect(bounceEl).toBeVisible({ timeout: 10_000 });
    await expect(bounceEl).toContainText("bouncing text");
  });

  test("mentions render as links", async ({ page }) => {
    const marker = `mention-test-${Date.now()}`;
    await createNote(page, `hello @admin ${marker}`);
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = findNoteContent(page, marker);
    const mention = noteContent.locator("a.mention");
    await expect(mention).toBeVisible({ timeout: 10_000 });
    await expect(mention).toContainText("@admin");
  });

  test("plain text without MFM renders correctly", async ({ page }) => {
    const text = `plain text test ${Date.now()}`;
    await createNote(page, text);
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = findNoteContent(page, text);
    await expect(noteContent).toContainText(text, { timeout: 10_000 });
  });

  test("URL auto-linking works", async ({ page }) => {
    const marker = `url-test-${Date.now()}`;
    await createNote(page, `check https://example.com ${marker}`);
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = findNoteContent(page, marker);
    const link = noteContent.locator('a[href="https://example.com"]');
    await expect(link).toBeVisible({ timeout: 10_000 });
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", /noopener/);
  });

  test("markdown link opens in new tab", async ({ page }) => {
    const marker = `mdlink-test-${Date.now()}`;
    await createNote(page, `[Example](https://example.com) ${marker}`);
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = findNoteContent(page, marker);
    const link = noteContent.locator('a[href="https://example.com"]');
    await expect(link).toBeVisible({ timeout: 10_000 });
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", /noopener/);
  });

  test("mention links do not open in new tab", async ({ page }) => {
    const marker = `mention-newtab-${Date.now()}`;
    await createNote(page, `@admin ${marker}`);
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = findNoteContent(page, marker);
    const mention = noteContent.locator("a.mention");
    await expect(mention).toBeVisible({ timeout: 10_000 });
    const target = await mention.getAttribute("target");
    expect(target).toBeFalsy();
  });

  test("blur function applies blur class", async ({ page }) => {
    await createNote(page, "$[blur secret text]");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = findNoteContent(page, "secret text");
    const blurEl = noteContent.locator(".mfm-fn-blur");
    await expect(blurEl).toBeVisible({ timeout: 10_000 });
    await expect(blurEl).toContainText("secret text");
  });

  test("x2 scaling applies font-size", async ({ page }) => {
    await createNote(page, "$[x2 big text]");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = findNoteContent(page, "big text");
    const x2El = noteContent.locator(".mfm-fn").first();
    await expect(x2El).toBeVisible({ timeout: 10_000 });
    await expect(x2El).toContainText("big text");
    const fontSize = await x2El.evaluate((el) => el.style.fontSize);
    expect(fontSize).toBe("200%");
  });

  test("flip function applies transform", async ({ page }) => {
    await createNote(page, "$[flip flipped text]");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = findNoteContent(page, "flipped text");
    const flipEl = noteContent.locator(".mfm-fn").first();
    await expect(flipEl).toBeVisible({ timeout: 10_000 });
    await expect(flipEl).toContainText("flipped text");
    const transform = await flipEl.evaluate((el) => el.style.transform);
    expect(transform).toBe("scaleX(-1)");
  });

  test("center text renders with center alignment", async ({ page }) => {
    await createNote(page, "<center>centered text</center>");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = findNoteContent(page, "centered text");
    const centerEl = noteContent.locator(".mfm-center");
    await expect(centerEl).toBeVisible({ timeout: 10_000 });
    await expect(centerEl).toContainText("centered text");
  });

  test("blockquote renders correctly", async ({ page }) => {
    await createNote(page, "> quoted text");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = findNoteContent(page, "quoted text");
    const quote = noteContent.locator("blockquote.mfm-quote");
    await expect(quote).toBeVisible({ timeout: 10_000 });
    await expect(quote).toContainText("quoted text");
  });

  test("combined MFM formatting works", async ({ page }) => {
    await createNote(page, "**bold** and $[shake animated] and `code`");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = findNoteContent(page, "animated");
    await expect(noteContent.locator("strong")).toContainText("bold", { timeout: 10_000 });
    await expect(noteContent.locator(".mfm-fn-shake")).toContainText("animated");
    await expect(noteContent.locator("code.mfm-inline-code")).toContainText("code");
  });
});
