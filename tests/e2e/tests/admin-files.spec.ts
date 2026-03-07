import { test, expect } from "@playwright/test";
import { loginAsAdmin, goToAdminTab, png1x1 } from "./helpers";

test.describe("Admin Server Files", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("upload a file and see it listed", async ({ page }) => {
    await goToAdminTab(page, "Files");

    const uniqueName = `upload_${Date.now()}.png`;
    const fileInput = page.locator('.admin-emoji-actions input[type="file"]');
    await fileInput.setInputFiles({
      name: uniqueName,
      mimeType: "image/png",
      buffer: png1x1(),
    });

    // Wait for the file to appear in the list
    const fileItem = page.locator(".admin-file-item").filter({ hasText: uniqueName });
    await expect(fileItem).toBeVisible({ timeout: 10_000 });
    // Should show a thumbnail for images
    await expect(fileItem.locator(".admin-file-thumb")).toBeVisible();
  });

  test("delete a file", async ({ page }) => {
    await goToAdminTab(page, "Files");

    const uniqueName = `del_${Date.now()}.png`;
    const fileInput = page.locator('.admin-emoji-actions input[type="file"]');
    await fileInput.setInputFiles({
      name: uniqueName,
      mimeType: "image/png",
      buffer: png1x1(),
    });
    const fileItem = page.locator(".admin-file-item").filter({ hasText: uniqueName });
    await expect(fileItem).toBeVisible({ timeout: 10_000 });

    // Accept confirm dialog
    page.on("dialog", (dialog) => dialog.accept());

    // Click delete on the specific item
    await fileItem.locator(".btn-danger").click();

    // The specific file should no longer be visible
    await expect(fileItem).not.toBeVisible({ timeout: 5_000 });
  });

  test("copy URL button works", async ({ page }) => {
    await goToAdminTab(page, "Files");

    const uniqueName = `copy_${Date.now()}.png`;
    const fileInput = page.locator('.admin-emoji-actions input[type="file"]');
    await fileInput.setInputFiles({
      name: uniqueName,
      mimeType: "image/png",
      buffer: png1x1(),
    });
    const fileItem = page.locator(".admin-file-item").filter({ hasText: uniqueName });
    await expect(fileItem).toBeVisible({ timeout: 10_000 });

    // Click copy URL on the specific item
    await fileItem.locator('button:has-text("Copy")').click();

    // Button text should change to "Copied!" momentarily
    await expect(fileItem.locator('button:has-text("Copied")')).toBeVisible({ timeout: 3_000 });
  });
});
