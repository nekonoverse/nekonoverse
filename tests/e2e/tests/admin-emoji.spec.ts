import { test, expect } from "@playwright/test";
import { loginAsAdmin, goToAdminTab, png1x1 } from "./helpers";

test.describe("Admin Emoji Management", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("emoji tab loads", async ({ page }) => {
    await goToAdminTab(page, "Emoji");
    // Should show the emoji management section (empty state or emoji list)
    await expect(page.locator(".admin-emoji-actions")).toBeVisible({ timeout: 5_000 });
  });

  test("add emoji form opens and closes", async ({ page }) => {
    await goToAdminTab(page, "Emoji");

    // Click "Add Emoji" button
    await page.click('.admin-emoji-actions button:has-text("Add")');
    await expect(page.locator(".admin-emoji-form")).toBeVisible();

    // Click again to close
    await page.click('.admin-emoji-actions button:has-text("Add")');
    await expect(page.locator(".admin-emoji-form")).not.toBeVisible();
  });

  test("add emoji with shortcode and metadata", async ({ page }) => {
    await goToAdminTab(page, "Emoji");

    // Open add form
    await page.click('.admin-emoji-actions button:has-text("Add")');
    await expect(page.locator(".admin-emoji-form")).toBeVisible();

    // Fill in the form
    const fileInput = page.locator('.admin-emoji-form input[type="file"]');
    await fileInput.setInputFiles({
      name: "test_emoji.png",
      mimeType: "image/png",
      buffer: png1x1(),
    });

    const uniqueCode = `e2e_emoji_${Date.now()}`;
    await page.fill('.admin-emoji-form input[placeholder="neko_smile"]', uniqueCode);
    // Fill category
    const categoryInput = page.locator('.admin-emoji-form .settings-form-group').filter({ hasText: "Category" }).locator("input");
    await categoryInput.fill("e2e_test");
    // Fill license
    const licenseInput = page.locator('.admin-emoji-form .settings-form-group').filter({ hasText: "License" }).locator("input");
    await licenseInput.fill("CC0");

    // Submit
    await page.click('.admin-emoji-form button:has-text("Add")');

    // Wait for the form to close and the emoji to appear in the list
    await expect(page.locator(".admin-emoji-form")).not.toBeVisible({ timeout: 10_000 });
    const emojiItem = page.locator(".admin-emoji-item").filter({ hasText: `:${uniqueCode}:` });
    await expect(emojiItem).toBeVisible();
    await expect(emojiItem.locator(".admin-emoji-cat")).toContainText("e2e_test");
  });

  test("delete emoji", async ({ page }) => {
    await goToAdminTab(page, "Emoji");

    // First add an emoji to delete
    await page.click('.admin-emoji-actions button:has-text("Add")');
    const fileInput = page.locator('.admin-emoji-form input[type="file"]');
    await fileInput.setInputFiles({
      name: "to_delete.png",
      mimeType: "image/png",
      buffer: png1x1(),
    });
    await page.fill('.admin-emoji-form input[placeholder="neko_smile"]', "e2e_delete_me");
    await page.click('.admin-emoji-form button:has-text("Add")');
    const emojiItem = page.locator(".admin-emoji-item").filter({ hasText: ":e2e_delete_me:" });
    await expect(emojiItem).toBeVisible({ timeout: 10_000 });

    // Count items before deletion
    const countBefore = await page.locator(".admin-emoji-item").count();

    // Accept the confirm dialog
    page.on("dialog", (dialog) => dialog.accept());

    // Delete the specific emoji
    await emojiItem.locator(".btn-danger").click();

    // Item count should decrease
    await expect(page.locator(".admin-emoji-item")).toHaveCount(countBefore - 1, { timeout: 5_000 });
  });

  test("export link exists", async ({ page }) => {
    await goToAdminTab(page, "Emoji");
    const exportLink = page.locator('a:has-text("Export")');
    await expect(exportLink).toBeVisible();
    await expect(exportLink).toHaveAttribute("href", /emoji\/export/);
  });
});
