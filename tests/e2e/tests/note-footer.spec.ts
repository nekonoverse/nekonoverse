import { test, expect } from "@playwright/test";
import { loginAsAdmin, createNote } from "./helpers";

test.describe("Note Footer", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("note footer items are vertically aligned", async ({ page }) => {
    // Create and edit a note so the "edited" label appears
    const text = `Footer align ${Date.now()}`;
    const note = await createNote(page, text);
    await page.request.put(`/api/v1/statuses/${note.id}`, {
      data: { content: `${text} edited` },
    });

    await page.goto("/");
    const noteCard = page.locator(".note-card").filter({ hasText: `${text} edited` });
    await expect(noteCard).toBeVisible({ timeout: 10_000 });

    // Verify footer has align-items: center (CSS may not be applied immediately)
    const footer = noteCard.locator(".note-footer");
    await expect(footer).toBeVisible();
    await expect(async () => {
      const alignItems = await footer.evaluate(
        (el) => window.getComputedStyle(el).alignItems,
      );
      expect(alignItems).toBe("center");
    }).toPass({ timeout: 5_000 });

    // Verify edited label and time link are present
    await expect(noteCard.locator(".note-edited-label")).toBeVisible();
    await expect(noteCard.locator(".note-time-link")).toBeVisible();
  });

  test("unixtime format shows clock icon", async ({ page }) => {
    // Create a note first
    await createNote(page, `Clock icon test ${Date.now()}`);

    // Switch to unixtime format in settings
    await page.goto("/settings/appearance");
    await expect(page.locator(".theme-selector").first()).toBeVisible({ timeout: 15_000 });
    await page.click('.theme-btn:has-text("Unixtime")');

    // Go back to timeline and check for clock icon
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteTime = page.locator(".note-time").first();
    await expect(noteTime).toBeVisible();

    // Clock icon should be present
    const clockIcon = noteTime.locator(".note-time-icon");
    await expect(clockIcon).toBeVisible();

    // Time should be a unix timestamp (numeric)
    const timeText = await noteTime.textContent();
    expect(timeText!.trim()).toMatch(/^\d+$/);

    // Reset time format back to absolute
    await page.goto("/settings/appearance");
    await expect(page.locator(".theme-selector").first()).toBeVisible({ timeout: 15_000 });
    await page.click('.theme-btn:has-text("Absolute")');
  });

  test("non-unixtime format does not show clock icon", async ({ page }) => {
    await createNote(page, `No clock test ${Date.now()}`);

    // Ensure absolute format is selected
    await page.goto("/settings/appearance");
    await expect(page.locator(".theme-selector").first()).toBeVisible({ timeout: 15_000 });
    await page.click('.theme-btn:has-text("Absolute")');

    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteTime = page.locator(".note-time").first();
    await expect(noteTime).toBeVisible();

    // Clock icon should not be present
    const clockIcon = noteTime.locator(".note-time-icon");
    await expect(clockIcon).toHaveCount(0);
  });
});
