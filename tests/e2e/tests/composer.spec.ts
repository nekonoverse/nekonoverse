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
