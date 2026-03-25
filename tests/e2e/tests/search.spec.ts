import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test.describe("Search", () => {
  test("search page renders form and accepts input", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/search");
    await page.waitForSelector(".search-form", { timeout: 10_000 });

    const input = page.locator(".search-input");
    await expect(input).toBeVisible();
    await input.fill("test");
    await expect(input).toHaveValue("test");
  });

  test("search for nonexistent term shows no results", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/search");
    await page.waitForSelector(".search-form", { timeout: 10_000 });

    await page.fill(".search-input", `nonexistent_term_${Date.now()}`);
    await page.click('.search-form .btn[type="submit"]');

    await page.waitForSelector(".empty", { timeout: 10_000 });
    const emptyText = await page.textContent(".empty");
    expect(emptyText).toBeTruthy();
  });
});
