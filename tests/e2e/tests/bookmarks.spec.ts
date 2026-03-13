import { test, expect } from "@playwright/test";
import { loginAsAdmin, createNote } from "./helpers";

test.describe("Bookmarks", () => {
  test("bookmarked note appears on bookmarks page", async ({ page }) => {
    await loginAsAdmin(page);
    const uid = Date.now();
    const note = await createNote(page, `bookmark-e2e-${uid}`);

    // Bookmark via API
    const resp = await page.request.post(
      `/api/v1/statuses/${note.id}/bookmark`,
    );
    expect(resp.ok()).toBeTruthy();

    await page.goto("/bookmarks");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const content = await page.textContent(".page-container");
    expect(content).toContain(`bookmark-e2e-${uid}`);
  });

  test("unbookmarked note disappears from bookmarks page", async ({ page }) => {
    await loginAsAdmin(page);
    const uid = Date.now();
    const note = await createNote(page, `unbookmark-e2e-${uid}`);

    await page.request.post(`/api/v1/statuses/${note.id}/bookmark`);

    // Unbookmark
    await page.request.post(`/api/v1/statuses/${note.id}/unbookmark`);

    await page.goto("/bookmarks");
    // ノートが表示されないか、空メッセージが出ること
    const empty = page.locator(".empty");
    const card = page.locator(`.note-card:has-text("unbookmark-e2e-${uid}")`);
    // どちらかが真: 空メッセージが表示される or 該当ノートがない
    const hasEmpty = await empty.isVisible().catch(() => false);
    const hasCard = await card.isVisible().catch(() => false);
    expect(hasCard).toBeFalsy();
  });
});
