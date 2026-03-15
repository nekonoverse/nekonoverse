import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test.describe("Navbar timeline icon switching", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("shows globe icon on public timeline", async ({ page }) => {
    await page.goto("/");
    const btn = page.locator(".navbar-tl-wrap > button.navbar-icon");
    await expect(btn).toBeVisible({ timeout: 5_000 });
    await expect(btn).toHaveScreenshot("tl-icon-globe.png");
  });

  test("shows house icon on home timeline", async ({ page }) => {
    await page.goto("/?tl=home");
    const btn = page.locator(".navbar-tl-wrap > button.navbar-icon");
    await expect(btn).toBeVisible({ timeout: 5_000 });
    await expect(btn).toHaveScreenshot("tl-icon-house.png");
  });

  test("icon switches when navigating via dropdown", async ({ page }) => {
    // Start on public timeline — globe icon
    await page.goto("/");
    const btn = page.locator(".navbar-tl-wrap > button.navbar-icon");
    await expect(btn).toBeVisible({ timeout: 5_000 });
    await expect(btn).toHaveScreenshot("tl-icon-globe.png");

    // Open dropdown and switch to home timeline
    await btn.click();
    await expect(page.locator(".navbar-tl-dropdown")).toBeVisible();
    await page.locator('.navbar-tl-dropdown a[href="/?tl=home"]').click();

    // Should now show house icon
    await expect(btn).toHaveScreenshot("tl-icon-house.png");

    // Open dropdown and switch back to public timeline
    await btn.click();
    await expect(page.locator(".navbar-tl-dropdown")).toBeVisible();
    await page.locator('.navbar-tl-dropdown a[href="/"]').click();

    // Should now show globe icon again
    await expect(btn).toHaveScreenshot("tl-icon-globe.png");
  });

  test("icon updates with browser back/forward", async ({ page }) => {
    // Start on public timeline — globe
    await page.goto("/");
    const btn = page.locator(".navbar-tl-wrap > button.navbar-icon");
    await expect(btn).toHaveScreenshot("tl-icon-globe.png");

    // Navigate to home timeline via dropdown
    await btn.click();
    await page.locator('.navbar-tl-dropdown a[href="/?tl=home"]').click();
    await expect(btn).toHaveScreenshot("tl-icon-house.png");

    // Browser back → public timeline (globe)
    await page.goBack();
    await expect(btn).toHaveScreenshot("tl-icon-globe.png");

    // Browser forward → home timeline (house)
    await page.goForward();
    await expect(btn).toHaveScreenshot("tl-icon-house.png");
  });

  test("icon correct after navigating away and back", async ({ page }) => {
    // Start on home timeline
    await page.goto("/?tl=home");
    const btn = page.locator(".navbar-tl-wrap > button.navbar-icon");
    await expect(btn).toHaveScreenshot("tl-icon-house.png");

    // Navigate to notifications
    await page.click('a[href="/notifications"]');
    await expect(page).toHaveURL(/\/notifications/);

    // Navigate to public timeline
    await page.goto("/");
    await expect(btn).toHaveScreenshot("tl-icon-globe.png");
  });

  test("dropdown highlights active timeline correctly", async ({ page }) => {
    // On public timeline — open dropdown
    await page.goto("/");
    const btn = page.locator(".navbar-tl-wrap > button.navbar-icon");
    await btn.click();
    const dropdown = page.locator(".navbar-tl-dropdown");
    await expect(dropdown).toBeVisible();
    await expect(dropdown).toHaveScreenshot("tl-dropdown-public-active.png");

    // Switch to home timeline — open dropdown
    await page.locator('.navbar-tl-dropdown a[href="/?tl=home"]').click();
    await btn.click();
    await expect(dropdown).toBeVisible();
    await expect(dropdown).toHaveScreenshot("tl-dropdown-home-active.png");
  });
});
