import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test.describe("User Settings", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("settings page loads with category menu", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.locator(".settings-menu")).toBeVisible({ timeout: 15_000 });
    await expect(page.locator(".settings-menu-card").first()).toBeVisible();
  });

  test("can navigate to sub-page and back", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.locator(".settings-menu")).toBeVisible({ timeout: 15_000 });

    // Click Appearance card
    await page.click('.settings-menu-card:has-text("Appearance")');
    // Theme selector should be visible
    await expect(page.locator(".theme-selector").first()).toBeVisible({ timeout: 5_000 });
    // Breadcrumb should be visible
    await expect(page.locator(".breadcrumb")).toBeVisible();

    // Click breadcrumb link to go back
    await page.click(".breadcrumb-link");
    await expect(page.locator(".settings-menu")).toBeVisible({ timeout: 5_000 });
  });

  test("can switch theme", async ({ page }) => {
    await page.goto("/settings/appearance");
    await expect(page.locator(".theme-selector").first()).toBeVisible({ timeout: 15_000 });

    // Click Light theme button
    await page.click('.theme-btn:has-text("Light")');

    // The html element should have data-theme="light"
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

    // Switch back to Dark (dark is the default, attribute is removed)
    await page.click('.theme-btn:has-text("Dark")');
    await expect(page.locator("html")).not.toHaveAttribute("data-theme");
  });
});
