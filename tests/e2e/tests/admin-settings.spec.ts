import { test, expect } from "@playwright/test";
import { loginAsAdmin, goToAdminTab, png1x1 } from "./helpers";

test.describe("Admin Server Settings", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("settings tab loads and shows form", async ({ page }) => {
    await goToAdminTab(page, "Server Settings");
    // Should show the server settings heading and form fields
    await expect(page.locator(".settings-section h3").first()).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('.settings-form-group input[type="text"]').first()).toBeVisible();
  });

  test("save server name", async ({ page }) => {
    await goToAdminTab(page, "Server Settings");
    await expect(page.locator(".settings-section h3").first()).toBeVisible({ timeout: 10_000 });

    // Fill in server name
    const nameInput = page.locator(".settings-form-group").first().locator("input");
    await nameInput.fill("E2E Test Server");

    // Click save
    await page.click('.settings-section button:has-text("Save")');

    // Should show success message
    await expect(page.locator(".settings-success")).toBeVisible({ timeout: 5_000 });
  });

  test("server name persists after reload", async ({ page }) => {
    await goToAdminTab(page, "Server Settings");
    await expect(page.locator(".settings-section h3").first()).toBeVisible({ timeout: 10_000 });

    // Set a name
    const nameInput = page.locator(".settings-form-group").first().locator("input");
    await nameInput.fill("Persistent Name");
    await page.click('.settings-section button:has-text("Save")');
    await expect(page.locator(".settings-success")).toBeVisible({ timeout: 5_000 });

    // Reload page
    await goToAdminTab(page, "Server Settings");
    await expect(page.locator(".settings-section h3").first()).toBeVisible({ timeout: 10_000 });

    // Name should be preserved
    const value = await page.locator(".settings-form-group").first().locator("input").inputValue();
    expect(value).toBe("Persistent Name");
  });

  test("upload server icon shows preview", async ({ page }) => {
    await goToAdminTab(page, "Server Settings");
    await expect(page.locator(".settings-section h3").first()).toBeVisible({ timeout: 10_000 });

    // Find the hidden file input for the icon (accepts specific image types)
    const fileInput = page.locator('.settings-section input[type="file"]');
    await fileInput.setInputFiles({
      name: "icon.png",
      mimeType: "image/png",
      buffer: png1x1(),
    });

    // Should show the icon preview
    await expect(page.locator(".admin-server-icon-preview")).toBeVisible({ timeout: 10_000 });
  });
});
