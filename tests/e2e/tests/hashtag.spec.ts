import { test, expect } from "@playwright/test";
import { loginAsAdmin, createNote } from "./helpers";

test.describe("Hashtag", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("create note with hashtag and navigate to tag timeline", async ({ page }) => {
    const tag = `e2etag${Date.now()}`;
    const text = `Hello #${tag} world`;

    // Create note with hashtag
    const note = await createNote(page, text);
    expect(note.id).toBeTruthy();

    // Navigate to the tag timeline
    await page.goto(`/tags/${tag}`);

    // Wait for the tag timeline header
    await expect(page.locator(".tag-timeline-header")).toContainText(`#${tag}`, {
      timeout: 10_000,
    });

    // The note should appear on the tag timeline
    await expect(
      page.locator(".note-card").filter({ hasText: tag }),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("hashtag link in note navigates to tag timeline", async ({ page }) => {
    const tag = `clicktag${Date.now()}`;
    await createNote(page, `Testing #${tag} click`);

    // Go to home timeline
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    // Find the hashtag link and click it
    const hashtagLink = page.locator(`.mfm-hashtag:has-text("#${tag}")`).first();
    await expect(hashtagLink).toBeVisible({ timeout: 10_000 });
    await hashtagLink.click();

    // Should navigate to the tag timeline
    await expect(page).toHaveURL(new RegExp(`/tags/${tag}`), { timeout: 10_000 });
    await expect(page.locator(".tag-timeline-header")).toContainText(`#${tag}`);
  });

  test("empty tag timeline shows empty message", async ({ page }) => {
    await page.goto("/tags/nonexistenttag999");
    await expect(page.locator(".empty")).toBeVisible({ timeout: 10_000 });
  });

  test("trending tags endpoint returns data", async ({ page }) => {
    // Create some notes with a hashtag first
    const tag = `trend${Date.now()}`;
    for (let i = 0; i < 3; i++) {
      await createNote(page, `Trending post ${i} #${tag}`);
    }

    const resp = await page.request.get("/api/v1/trends/tags");
    expect(resp.status()).toBe(200);
    const data = await resp.json();
    expect(Array.isArray(data)).toBe(true);
  });
});
