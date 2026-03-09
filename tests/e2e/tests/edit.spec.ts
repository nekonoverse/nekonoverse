import { test, expect } from "@playwright/test";
import { loginAsAdmin, createNote } from "./helpers";

test.describe("Note Editing", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("can edit a note and see edited label", async ({ page }) => {
    const originalText = `Original ${Date.now()}`;
    const editedText = `Edited ${Date.now()}`;

    // Create a note via API
    await createNote(page, originalText);

    // Navigate to home to see the note
    await page.goto("/");
    await expect(page.locator(".note-card").filter({ hasText: originalText })).toBeVisible({
      timeout: 10_000,
    });

    // Open the "..." menu on the note
    const noteCard = page.locator(".note-card").filter({ hasText: originalText });
    await noteCard.locator(".note-more-btn").click();

    // Wait for dropdown to appear
    const editBtn = noteCard.locator(".note-more-item").filter({ hasText: /Edit|編集/ });
    await expect(editBtn).toBeVisible({ timeout: 5_000 });

    // Click the Edit button
    await editBtn.click();

    // The edit textarea should appear
    await expect(noteCard.locator(".note-edit-textarea")).toBeVisible({ timeout: 10_000 });

    // Clear and type new content
    await noteCard.locator(".note-edit-textarea").fill(editedText);

    // Click Save
    await noteCard.locator(".note-edit-save-btn").click();

    // The edited content should appear and the textarea should be gone
    await expect(noteCard.locator(".note-edit-textarea")).not.toBeVisible({ timeout: 5_000 });
    await expect(noteCard.locator(".note-edited-label")).toBeVisible({ timeout: 5_000 });
  });
});
