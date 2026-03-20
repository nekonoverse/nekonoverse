import { test, expect } from "@playwright/test";
import { loginAsAdmin, createNote } from "./helpers";

/** Strip HTML tags to get plain text for Playwright text matching. */
function stripHtml(html: string): string {
  return html.replace(/<[^>]+>/g, "");
}

test.describe("Thread View", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("create a reply and verify thread view shows both", async ({ page }) => {
    // Create a parent note via API
    const parent = await createNote(page, `Thread parent ${Date.now()}`);
    const parentId = parent.id;

    // Create a reply via API
    const replyResp = await page.request.post("/api/v1/statuses", {
      data: {
        content: `Thread reply ${Date.now()}`,
        visibility: "public",
        in_reply_to_id: parentId,
      },
    });
    expect(replyResp.status()).toBe(201);
    const reply = await replyResp.json();

    // Navigate to thread view
    await page.goto(`/notes/${parentId}`);

    // Wait for thread to load
    await expect(page.locator(".thread-view")).toBeVisible({ timeout: 10_000 });

    // The target note should be highlighted
    await expect(page.locator(".thread-target-note")).toBeVisible();

    // The reply should appear in descendants
    await expect(
      page.locator(".thread-descendant-note .note-card").filter({
        hasText: stripHtml(reply.content),
      }),
    ).toBeVisible({ timeout: 5_000 });
  });

  test("thread view shows ancestors when viewing a reply", async ({ page }) => {
    const parent = await createNote(page, `Ancestor test ${Date.now()}`);

    const replyResp = await page.request.post("/api/v1/statuses", {
      data: {
        content: `Child of ancestor ${Date.now()}`,
        visibility: "public",
        in_reply_to_id: parent.id,
      },
    });
    expect(replyResp.status()).toBe(201);
    const reply = await replyResp.json();

    // Navigate to the reply's thread view
    await page.goto(`/notes/${reply.id}`);
    await expect(page.locator(".thread-view")).toBeVisible({ timeout: 10_000 });

    // The parent should appear in ancestors
    await expect(
      page.locator(".thread-ancestor-note .note-card").filter({
        hasText: stripHtml(parent.content),
      }),
    ).toBeVisible({ timeout: 5_000 });
  });

  test("clicking timestamp opens thread modal on timeline", async ({ page }) => {
    const note = await createNote(page, `Timestamp link ${Date.now()}`);

    // Go to timeline
    await page.goto("/");
    await expect(page.locator(".timeline")).toBeVisible({ timeout: 10_000 });

    // Click the timestamp link of the note
    const noteCard = page.locator(".note-card").filter({
      hasText: stripHtml(note.content),
    });
    await expect(noteCard).toBeVisible({ timeout: 5_000 });
    await noteCard.locator(".note-time-link").click();

    // Should open thread modal (not navigate)
    await expect(page.locator(".thread-modal")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(".thread-modal .thread-view")).toBeVisible({ timeout: 10_000 });

    // URL should stay on timeline
    await expect(page).toHaveURL("/", { timeout: 5_000 });
  });

  test("direct navigation to /notes/:id still works", async ({ page }) => {
    const note = await createNote(page, `Direct nav ${Date.now()}`);

    // Navigate directly to thread view
    await page.goto(`/notes/${note.id}`);
    await expect(page.locator(".thread-view")).toBeVisible({ timeout: 10_000 });
  });
});
