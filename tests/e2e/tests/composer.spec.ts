import { test, expect } from "@playwright/test";
import { loginAsAdmin, png1x1 } from "./helpers";

test.describe("Note Composer", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("composer form is visible on home page", async ({ page }) => {
    await expect(page.locator("form.note-composer")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator("form.note-composer textarea")).toBeVisible();
    await expect(page.locator("button.composer-post-btn")).toBeVisible();
  });

  test("can post a text note", async ({ page }) => {
    const text = `Composer test ${Date.now()}`;
    await page.locator("form.note-composer textarea").fill(text);
    await page.click("button.composer-post-btn");

    // Note should appear in timeline
    await expect(page.locator(".note-card").filter({ hasText: text })).toBeVisible({
      timeout: 10_000,
    });

    // Textarea should be cleared after posting
    await expect(page.locator("form.note-composer textarea")).toHaveValue("");
  });

  test("inline emoji suggest opens on colon and closes on Escape", async ({ page }) => {
    const composerForm = page.locator("form.note-composer");
    await expect(composerForm).toBeVisible({ timeout: 10_000 });

    const textarea = composerForm.locator("textarea");
    await textarea.click();
    await textarea.type(":smi");

    // Inline suggest should appear
    await expect(page.locator(".emoji-suggest")).toBeVisible({ timeout: 5_000 });
    await expect(page.locator(".emoji-suggest-item").first()).toBeVisible();

    // Close by pressing Escape
    await page.keyboard.press("Escape");
    await expect(page.locator(".emoji-suggest")).not.toBeVisible({ timeout: 5_000 });
  });

  test("can insert emoji via inline suggest", async ({ page }) => {
    const composerForm = page.locator("form.note-composer");
    await expect(composerForm).toBeVisible({ timeout: 10_000 });

    const textarea = composerForm.locator("textarea");
    await textarea.click();
    await textarea.type("Hello :smi");

    // Suggest should appear with results
    await expect(page.locator(".emoji-suggest")).toBeVisible({ timeout: 5_000 });
    await expect(page.locator(".emoji-suggest-item").first()).toBeVisible();

    // Select first item with Enter
    await page.keyboard.press("Enter");

    // Suggest should close and textarea should contain the emoji (not the :smi query)
    await expect(page.locator(".emoji-suggest")).not.toBeVisible({ timeout: 5_000 });
    const value = await textarea.inputValue();
    expect(value.startsWith("Hello ")).toBe(true);
    expect(value).not.toContain(":smi");
  });

  test("emoji button opens full emoji picker", async ({ page }) => {
    const composerForm = page.locator("form.note-composer");
    await expect(composerForm).toBeVisible({ timeout: 10_000 });

    // Find the emoji button by its SVG smiley circle
    const smileBtn = composerForm.locator("button.composer-attach-btn:has(svg circle[r='10'])");
    await smileBtn.click();

    // Full emoji picker should be visible
    await expect(page.locator(".emoji-picker")).toBeVisible({ timeout: 5_000 });
    await expect(page.locator(".emoji-search")).toBeVisible();
  });

  test("post button is disabled while uploading media", async ({ page }) => {
    const composerForm = page.locator("form.note-composer");
    await expect(composerForm).toBeVisible({ timeout: 10_000 });

    // Intercept media upload API and delay the response
    let resolveUpload!: () => void;
    const uploadGate = new Promise<void>((r) => { resolveUpload = r; });
    await page.route("**/api/v1/media", async (route) => {
      await uploadGate;
      await route.continue();
    });

    // Trigger file upload via the hidden file input
    const fileInput = composerForm.locator('input[type="file"]');
    await fileInput.setInputFiles({
      name: "test.png",
      mimeType: "image/png",
      buffer: png1x1(),
    });

    // While uploading, post button should be disabled
    const postBtn = page.locator("button.composer-post-btn");
    await expect(postBtn).toBeDisabled({ timeout: 5_000 });

    // Resolve upload and verify button becomes enabled
    resolveUpload();
    await expect(postBtn).toBeEnabled({ timeout: 10_000 });
  });

  test("can change visibility", async ({ page }) => {
    // Open the visibility dropdown
    await page.click("button.composer-vis-toggle");
    await expect(page.locator(".composer-vis-dropdown")).toBeVisible();

    // Select "Followers" visibility
    await page.click('.composer-vis-item:has-text("Followers")');

    // Dropdown should close
    await expect(page.locator(".composer-vis-dropdown")).not.toBeVisible();
  });
});
