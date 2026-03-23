import { test, expect } from "@playwright/test";
import { loginAsAdmin, goToAdminTab, png1x1 } from "./helpers";

/** Click an emoji sub-tab inside the admin emoji page. */
async function goToEmojiSubTab(page: import("@playwright/test").Page, label: string) {
  await page.locator(`.settings-tabs .settings-tab`, { hasText: label }).click();
}

test.describe("Admin Emoji Management", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("emoji tab loads with sub-tabs", async ({ page }) => {
    await goToAdminTab(page, "Emoji");
    // All 4 sub-tabs should be visible
    const tabs = page.locator(".settings-tabs .settings-tab");
    await expect(tabs).toHaveCount(4, { timeout: 5_000 });
  });

  test("upload tab shows form immediately", async ({ page }) => {
    await goToAdminTab(page, "Emoji");
    await goToEmojiSubTab(page, "Upload");
    await expect(page.locator(".admin-emoji-form")).toBeVisible();
    await expect(page.locator('.admin-emoji-form input[type="file"]')).toBeVisible();
  });

  test("add emoji with shortcode and metadata", async ({ page }) => {
    await goToAdminTab(page, "Emoji");
    await goToEmojiSubTab(page, "Upload");

    const form = page.locator(".admin-emoji-form");
    await expect(form).toBeVisible();

    // Upload file
    const fileInput = form.locator('input[type="file"]');
    await fileInput.setInputFiles({
      name: "test_emoji.png",
      mimeType: "image/png",
      buffer: png1x1(),
    });

    const uniqueCode = `e2e_emoji_${Date.now()}`;
    // Shortcode input (inside EmojiEditForm)
    const shortcodeInput = form.locator('.emoji-import-field').filter({ hasText: /shortcode/i }).locator("input");
    await shortcodeInput.fill(uniqueCode);
    // Fill category
    const categoryInput = form.locator('.emoji-import-field').filter({ hasText: /category/i }).locator("input");
    await categoryInput.fill("e2e_test");
    // Fill license
    const licenseInput = form.locator('.emoji-import-field').filter({ hasText: /license/i }).locator("input");
    await licenseInput.fill("CC0");

    // Submit
    await form.locator('button:has-text("Add")').click();

    // Switch to Manage tab and verify the emoji appears in the grid
    await goToEmojiSubTab(page, "Manage");
    const emojiItem = page.locator(".admin-emoji-grid-item").filter({ hasText: `:${uniqueCode}:` });
    await expect(emojiItem).toBeVisible({ timeout: 10_000 });
  });

  test("delete emoji via edit modal", async ({ page }) => {
    await goToAdminTab(page, "Emoji");
    await goToEmojiSubTab(page, "Upload");

    // First add an emoji to delete
    const form = page.locator(".admin-emoji-form");
    const fileInput = form.locator('input[type="file"]');
    await fileInput.setInputFiles({
      name: "to_delete.png",
      mimeType: "image/png",
      buffer: png1x1(),
    });
    const shortcodeInput = form.locator('.emoji-import-field').filter({ hasText: /shortcode/i }).locator("input");
    await shortcodeInput.fill("e2e_delete_me");
    await form.locator('button:has-text("Add")').click();

    // Switch to Manage tab
    await goToEmojiSubTab(page, "Manage");
    const emojiItem = page.locator(".admin-emoji-grid-item").filter({ hasText: ":e2e_delete_me:" });
    await expect(emojiItem).toBeVisible({ timeout: 10_000 });

    // Count items before deletion
    const countBefore = await page.locator(".admin-emoji-grid-item").count();

    // Click emoji to open edit modal
    await emojiItem.click();
    const modal = page.locator(".modal-content");
    await expect(modal).toBeVisible({ timeout: 5_000 });

    // Click Delete button in delete zone
    await modal.locator(".admin-emoji-delete-zone .btn-danger").click();

    // Confirm deletion (second Delete button appears)
    await modal.locator(".admin-emoji-delete-zone").locator(".btn-danger").click();

    // Modal should close and item count should decrease
    await expect(page.locator(".modal-overlay")).not.toBeVisible({ timeout: 5_000 });
    await expect(page.locator(".admin-emoji-grid-item")).toHaveCount(countBefore - 1, { timeout: 5_000 });
  });

  test("export link exists in ZIP tab", async ({ page }) => {
    await goToAdminTab(page, "Emoji");
    await goToEmojiSubTab(page, "ZIP");
    const exportLink = page.locator('a:has-text("Export")');
    await expect(exportLink).toBeVisible();
    await expect(exportLink).toHaveAttribute("href", /emoji\/export/);
  });
});
