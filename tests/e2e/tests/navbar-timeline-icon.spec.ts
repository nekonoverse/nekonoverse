import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

/**
 * Navbar timeline icon switching tests.
 *
 * Verifies that the navbar correctly switches between globe (public TL)
 * and house (home TL) icons via DOM assertions (SVG element + title attribute).
 */
test.describe("Navbar timeline icon switching", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  /** Assert globe icon (public timeline) is shown */
  async function expectGlobeIcon(
    btn: ReturnType<typeof import("@playwright/test").Page.prototype.locator>,
  ) {
    await expect(btn).toHaveAttribute("title", "Public Timeline", {
      timeout: 5_000,
    });
    // Globe SVG contains <circle>, house SVG does not
    await expect(btn.locator("svg circle")).toBeVisible();
  }

  /** Assert house icon (home timeline) is shown */
  async function expectHouseIcon(
    btn: ReturnType<typeof import("@playwright/test").Page.prototype.locator>,
  ) {
    await expect(btn).toHaveAttribute("title", "Home", { timeout: 5_000 });
    // House SVG has no <circle>, confirming globe is gone
    await expect(btn.locator("svg circle")).not.toBeVisible();
  }

  test("shows globe icon on public timeline", async ({ page }) => {
    await page.goto("/");
    const btn = page.locator(".navbar-tl-wrap > button.navbar-icon");
    await expectGlobeIcon(btn);
  });

  test("shows house icon on home timeline", async ({ page }) => {
    await page.goto("/?tl=home");
    const btn = page.locator(".navbar-tl-wrap > button.navbar-icon");
    await expectHouseIcon(btn);
  });

  test("icon switches when navigating via dropdown", async ({ page }) => {
    await page.goto("/");
    const btn = page.locator(".navbar-tl-wrap > button.navbar-icon");
    await expectGlobeIcon(btn);

    // Switch to home timeline
    await btn.click();
    await expect(page.locator(".navbar-tl-dropdown")).toBeVisible();
    await page.locator('.navbar-tl-dropdown a[href="/?tl=home"]').click();
    await expectHouseIcon(btn);

    // Switch back to public timeline
    await btn.click();
    await expect(page.locator(".navbar-tl-dropdown")).toBeVisible();
    await page.locator('.navbar-tl-dropdown a[href="/"]').click();
    await expectGlobeIcon(btn);
  });

  test("icon updates with browser back/forward", async ({ page }) => {
    await page.goto("/");
    const btn = page.locator(".navbar-tl-wrap > button.navbar-icon");
    await expectGlobeIcon(btn);

    // Navigate to home timeline via dropdown
    await btn.click();
    await page.locator('.navbar-tl-dropdown a[href="/?tl=home"]').click();
    await expectHouseIcon(btn);

    // Browser back → public timeline
    await page.goBack();
    await expectGlobeIcon(btn);

    // Browser forward → home timeline
    await page.goForward();
    await expectHouseIcon(btn);
  });

  test("icon correct after navigating away and back", async ({ page }) => {
    await page.goto("/?tl=home");
    const btn = page.locator(".navbar-tl-wrap > button.navbar-icon");
    await expectHouseIcon(btn);

    // Navigate to notifications
    await page.click('a[href="/notifications"]');
    await expect(page).toHaveURL(/\/notifications/);

    // Navigate to public timeline
    await page.goto("/");
    await expectGlobeIcon(btn);
  });

  test("dropdown highlights active timeline correctly", async ({ page }) => {
    await page.goto("/");
    const btn = page.locator(".navbar-tl-wrap > button.navbar-icon");
    await btn.click();
    const dropdown = page.locator(".navbar-tl-dropdown");
    await expect(dropdown).toBeVisible();

    // Public timeline item should be active
    await expect(dropdown.locator('a[href="/"]')).toHaveClass(/active/);
    await expect(
      dropdown.locator('a[href="/?tl=home"]'),
    ).not.toHaveClass(/active/);

    // Switch to home timeline
    await page.locator('.navbar-tl-dropdown a[href="/?tl=home"]').click();
    await btn.click();
    await expect(dropdown).toBeVisible();

    // Home timeline item should now be active
    await expect(dropdown.locator('a[href="/?tl=home"]')).toHaveClass(/active/);
    await expect(dropdown.locator('a[href="/"]')).not.toHaveClass(/active/);
  });
});
