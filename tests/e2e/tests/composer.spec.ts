import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

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

  test("emoji picker opens and closes", async ({ page }) => {
    const composerForm = page.locator("form.note-composer");
    await expect(composerForm).toBeVisible({ timeout: 10_000 });

    // Emoji button should be visible
    const emojiBtn = composerForm.locator(".composer-emoji-wrap .composer-attach-btn");
    await expect(emojiBtn).toBeVisible();

    // Click to open picker
    await emojiBtn.click();
    await expect(page.locator(".emoji-picker")).toBeVisible({ timeout: 5_000 });
    await expect(page.locator(".emoji-search")).toBeVisible();

    // Click button again to close
    await emojiBtn.click();
    await expect(page.locator(".emoji-picker")).not.toBeVisible();
  });

  test("can insert emoji from picker into textarea", async ({ page }) => {
    const composerForm = page.locator("form.note-composer");
    await expect(composerForm).toBeVisible({ timeout: 10_000 });

    // Type some text first
    const textarea = composerForm.locator("textarea");
    await textarea.fill("Hello ");

    // Open emoji picker
    const emojiBtn = composerForm.locator(".composer-emoji-wrap .composer-attach-btn");
    await emojiBtn.click();
    await expect(page.locator(".emoji-picker")).toBeVisible({ timeout: 5_000 });

    // Click the first emoji button in the picker
    const firstEmoji = page.locator(".emoji-picker .emoji-btn").first();
    await firstEmoji.click({ timeout: 5_000 });

    // Picker should close and textarea should contain the emoji
    await expect(page.locator(".emoji-picker")).not.toBeVisible();
    const value = await textarea.inputValue();
    expect(value.startsWith("Hello ")).toBe(true);
    expect(value.length).toBeGreaterThan("Hello ".length);
  });

  test("emoji picker search filters results", async ({ page }) => {
    const composerForm = page.locator("form.note-composer");
    await expect(composerForm).toBeVisible({ timeout: 10_000 });

    // Open emoji picker
    const emojiBtn = composerForm.locator(".composer-emoji-wrap .composer-attach-btn");
    await emojiBtn.click();
    await expect(page.locator(".emoji-picker")).toBeVisible({ timeout: 5_000 });

    // Type a search query
    const searchInput = page.locator(".emoji-search");
    await searchInput.fill("heart");

    // Should show filtered results (at least one emoji)
    await expect(page.locator(".emoji-picker .emoji-btn").first()).toBeVisible({ timeout: 5_000 });
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
