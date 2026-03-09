import { test, expect } from "@playwright/test";
import { loginAsAdmin, createNote } from "./helpers";

test.describe("MFM Rendering", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("bold, italic, and strikethrough render correctly", async ({ page }) => {
    await createNote(page, "**bold text** *italic text* ~~strike text~~");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = page.locator(".note-content").first();
    await expect(noteContent.locator("strong")).toContainText("bold text");
    await expect(noteContent.locator("em")).toContainText("italic text");
    await expect(noteContent.locator("del")).toContainText("strike text");
  });

  test("inline code renders correctly", async ({ page }) => {
    await createNote(page, "here is `some code` inline");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = page.locator(".note-content").first();
    const code = noteContent.locator("code.mfm-inline-code");
    await expect(code).toBeVisible();
    await expect(code).toContainText("some code");
  });

  test("code block renders correctly", async ({ page }) => {
    await createNote(page, "```js\nconsole.log('hello');\n```");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = page.locator(".note-content").first();
    const codeBlock = noteContent.locator("pre.mfm-code-block code");
    await expect(codeBlock).toBeVisible();
    await expect(codeBlock).toContainText("console.log");
  });

  test("MFM shake function produces animated element", async ({ page }) => {
    await createNote(page, "$[shake shaking text]");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = page.locator(".note-content").first();
    const shakeEl = noteContent.locator(".mfm-fn-shake");
    await expect(shakeEl).toBeVisible();
    await expect(shakeEl).toContainText("shaking text");
  });

  test("MFM spin function produces animated element", async ({ page }) => {
    await createNote(page, "$[spin spinning text]");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = page.locator(".note-content").first();
    const spinEl = noteContent.locator(".mfm-fn-spin");
    await expect(spinEl).toBeVisible();
    await expect(spinEl).toContainText("spinning text");
  });

  test("MFM bounce function produces animated element", async ({ page }) => {
    await createNote(page, "$[bounce bouncing text]");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = page.locator(".note-content").first();
    const bounceEl = noteContent.locator(".mfm-fn-bounce");
    await expect(bounceEl).toBeVisible();
    await expect(bounceEl).toContainText("bouncing text");
  });

  test("mentions render as links", async ({ page }) => {
    await createNote(page, "hello @admin");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = page.locator(".note-content").first();
    const mention = noteContent.locator("a.mention");
    await expect(mention).toBeVisible();
    await expect(mention).toContainText("@admin");
  });

  test("plain text without MFM renders correctly", async ({ page }) => {
    const text = `plain text test ${Date.now()}`;
    await createNote(page, text);
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = page.locator(".note-content").first();
    await expect(noteContent).toContainText(text);
  });

  test("URL auto-linking works", async ({ page }) => {
    await createNote(page, "check https://example.com for info");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = page.locator(".note-content").first();
    const link = noteContent.locator('a[href="https://example.com"]');
    await expect(link).toBeVisible();
  });

  test("blur function applies blur class", async ({ page }) => {
    await createNote(page, "$[blur secret text]");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = page.locator(".note-content").first();
    const blurEl = noteContent.locator(".mfm-fn-blur");
    await expect(blurEl).toBeVisible();
    await expect(blurEl).toContainText("secret text");
  });

  test("x2 scaling applies font-size", async ({ page }) => {
    await createNote(page, "$[x2 big text]");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = page.locator(".note-content").first();
    const x2El = noteContent.locator(".mfm-fn").first();
    await expect(x2El).toBeVisible();
    await expect(x2El).toContainText("big text");
    const fontSize = await x2El.evaluate((el) => el.style.fontSize);
    expect(fontSize).toBe("200%");
  });

  test("flip function applies transform", async ({ page }) => {
    await createNote(page, "$[flip flipped text]");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = page.locator(".note-content").first();
    const flipEl = noteContent.locator(".mfm-fn").first();
    await expect(flipEl).toBeVisible();
    await expect(flipEl).toContainText("flipped text");
    const transform = await flipEl.evaluate((el) => el.style.transform);
    expect(transform).toBe("scaleX(-1)");
  });

  test("center text renders with center alignment", async ({ page }) => {
    await createNote(page, "<center>centered text</center>");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = page.locator(".note-content").first();
    const centerEl = noteContent.locator(".mfm-center");
    await expect(centerEl).toBeVisible();
    await expect(centerEl).toContainText("centered text");
  });

  test("blockquote renders correctly", async ({ page }) => {
    await createNote(page, "> quoted text");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = page.locator(".note-content").first();
    const quote = noteContent.locator("blockquote.mfm-quote");
    await expect(quote).toBeVisible();
    await expect(quote).toContainText("quoted text");
  });

  test("combined MFM formatting works", async ({ page }) => {
    await createNote(page, "**bold** and $[shake animated] and `code`");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteContent = page.locator(".note-content").first();
    await expect(noteContent.locator("strong")).toContainText("bold");
    await expect(noteContent.locator(".mfm-fn-shake")).toContainText("animated");
    await expect(noteContent.locator("code.mfm-inline-code")).toContainText("code");
  });
});
