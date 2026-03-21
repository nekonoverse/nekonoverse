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
    // SSEで同じノートが複数表示される場合があるため .first() を使用
    await expect(page.locator(".note-card").filter({ hasText: text }).first()).toBeVisible({
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
});
