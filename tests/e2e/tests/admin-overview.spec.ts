import { test, expect } from "@playwright/test";
import { loginAsAdmin, goToAdminTab, createNote } from "./helpers";

test.describe("Admin Overview", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("overview tab loads and displays stat cards", async ({ page }) => {
    await goToAdminTab(page, "Overview");

    const statsContainer = page.locator(".admin-stats");
    await expect(statsContainer).toBeVisible({ timeout: 10_000 });

    // 3 stat cards should be displayed (users, notes, domains)
    const cards = statsContainer.locator(".admin-stat-card");
    await expect(cards).toHaveCount(3);

    // Each card should have a number and a label
    for (let i = 0; i < 3; i++) {
      const num = cards.nth(i).locator(".admin-stat-num");
      const label = cards.nth(i).locator(".admin-stat-label");
      await expect(num).toBeVisible();
      await expect(label).toBeVisible();

      // Number should be a non-negative integer
      const text = await num.textContent();
      expect(Number(text)).toBeGreaterThanOrEqual(0);
      expect(Number.isInteger(Number(text))).toBe(true);
    }
  });

  test("note_count increases after creating a local note", async ({ page }) => {
    // Get current stats via API
    const before = await page.request.get("/api/v1/admin/stats");
    expect(before.status()).toBe(200);
    const statsBefore = await before.json();

    // Create a local note
    await createNote(page, `admin overview e2e ${Date.now()}`);

    // Get stats again
    const after = await page.request.get("/api/v1/admin/stats");
    expect(after.status()).toBe(200);
    const statsAfter = await after.json();

    expect(statsAfter.note_count).toBe(statsBefore.note_count + 1);
  });

  test("stats API returns expected schema", async ({ page }) => {
    const resp = await page.request.get("/api/v1/admin/stats");
    expect(resp.status()).toBe(200);

    const data = await resp.json();
    expect(data).toHaveProperty("user_count");
    expect(data).toHaveProperty("note_count");
    expect(data).toHaveProperty("domain_count");
    expect(typeof data.user_count).toBe("number");
    expect(typeof data.note_count).toBe("number");
    expect(typeof data.domain_count).toBe("number");
  });

  test("stats API is forbidden for unauthenticated requests", async ({
    page,
  }) => {
    // Clear session by using a fresh context
    await page.context().clearCookies();
    const resp = await page.request.get("/api/v1/admin/stats");
    expect(resp.status()).toBe(401);
  });
});
