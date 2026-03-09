import { test, expect } from "@playwright/test";
import { loginAsAdmin, createNote } from "./helpers";

test.describe("Note Editing", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("edited note shows edited label after API edit", async ({ page }) => {
    const originalText = `Original ${Date.now()}`;
    const editedText = `Edited ${Date.now()}`;

    // Create a note via API
    const note = await createNote(page, originalText);

    // Edit the note via API
    await page.request.put(`/api/v1/statuses/${note.id}`, {
      data: { content: editedText },
    });

    // Navigate to home to see the note
    await page.goto("/");
    await expect(page.locator(".note-card").filter({ hasText: editedText })).toBeVisible({
      timeout: 10_000,
    });

    // The "edited" label should be visible
    const noteCard = page.locator(".note-card").filter({ hasText: editedText });
    await expect(noteCard.locator(".note-edited-label")).toBeVisible({ timeout: 5_000 });
  });
});
