import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test.describe("User Settings", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("settings page loads with tabs", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.locator(".settings-tabs")).toBeVisible({ timeout: 15_000 });
  });

  test("can switch tabs", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.locator(".settings-tabs")).toBeVisible({ timeout: 15_000 });

    // Click Appearance tab
    await page.click('.settings-tab:has-text("Appearance")');
    // Theme selector should be visible
    await expect(page.locator(".theme-selector").first()).toBeVisible({ timeout: 5_000 });
  });

  test("can switch theme", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.locator(".settings-tabs")).toBeVisible({ timeout: 15_000 });
    await page.click('.settings-tab:has-text("Appearance")');
    await expect(page.locator(".theme-selector").first()).toBeVisible({ timeout: 5_000 });

    // Click Light theme button
    await page.click('.theme-btn:has-text("Light")');

    // The html element should have data-theme="light"
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

    // Switch back to Dark (dark is the default, attribute is removed)
    await page.click('.theme-btn:has-text("Dark")');
    await expect(page.locator("html")).not.toHaveAttribute("data-theme");
  });
});
