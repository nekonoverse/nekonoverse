import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test.describe("Search", () => {
  test("search for existing user returns results", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/search");
    await page.waitForSelector(".search-form", { timeout: 10_000 });

    await page.fill(".search-input", "admin");
    await page.click('.search-form .btn[type="submit"]');

    await page.waitForSelector(".search-result-item", { timeout: 10_000 });
    const handles = await page
      .locator(".search-result-handle")
      .allTextContents();
    expect(handles.some((h) => h.includes("admin"))).toBeTruthy();
  });

  test("search for nonexistent user shows no results", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/search");
    await page.waitForSelector(".search-form", { timeout: 10_000 });

    await page.fill(".search-input", `nonexistent_user_${Date.now()}`);
    await page.click('.search-form .btn[type="submit"]');

    // 空メッセージ or 結果なし
    await page.waitForSelector(".empty", { timeout: 10_000 });
    const emptyText = await page.textContent(".empty");
    expect(emptyText).toBeTruthy();
  });
});
