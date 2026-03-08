import { test, expect } from "@playwright/test";
import { loginAsAdmin, createNote } from "./helpers";

test.describe("Timeline", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("public timeline loads", async ({ page }) => {
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });
  });

  test("posting a note shows it on the timeline", async ({ page }) => {
    const text = `E2E timeline test ${Date.now()}`;
    await page.locator("form.note-composer textarea").fill(text);
    await page.click("button.composer-post-btn");

    // The new note should appear on the timeline
    await expect(page.locator(".note-card").filter({ hasText: text })).toBeVisible({
      timeout: 10_000,
    });
  });

  test("boosted note shows reblog banner", async ({ page }) => {
    // Create a note first via API
    const note = await createNote(page, `Boost target ${Date.now()}`);

    // Boost the note via API
    const boostResp = await page.request.post(`/api/v1/statuses/${note.id}/reblog`);
    expect(boostResp.status()).toBe(200);

    // Reload timeline
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    // The boosted note should have a reblog indicator
    await expect(page.locator(".note-reblog-indicator").first()).toBeVisible({ timeout: 5_000 });
  });

  test("note card visual regression", async ({ page }) => {
    // Ensure there's at least one note
    await createNote(page, "Visual regression test note");
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    const noteCard = page.locator(".note-card").first();
    await expect(noteCard).toBeVisible();
    await expect(noteCard).toHaveScreenshot("note-card.png");
  });

  test("boosted note card visual regression", async ({ page }) => {
    const note = await createNote(page, `Visual boost ${Date.now()}`);
    await page.request.post(`/api/v1/statuses/${note.id}/reblog`);

    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    // Find the boosted note (has reblog indicator)
    const boostedCard = page.locator(".note-card").filter({
      has: page.locator(".note-reblog-indicator"),
    }).first();
    await expect(boostedCard).toBeVisible({ timeout: 5_000 });
    await expect(boostedCard).toHaveScreenshot("boosted-note-card.png");
  });
});
