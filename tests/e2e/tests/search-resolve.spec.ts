import { test, expect } from "@playwright/test";
import { loginAsAdmin, createNote } from "./helpers";

test.describe("Search resolve", () => {
  test("resolve local note by AP URL via search modal", async ({ page }) => {
    await loginAsAdmin(page);

    // Create a note and get its URI (AP URL)
    const note = await createNote(page, "Resolve test note unique_resolve_e2e");
    const noteId = note.id;
    const noteUri = note.uri; // AP URL e.g. https://localhost/users/admin/statuses/{uuid}
    expect(noteUri).toBeTruthy();
    expect(noteUri).toContain("https://");

    // Open the search modal — the button title is "Lookup" (en) / "照会" (ja)
    await page.locator('button.navbar-icon[title="Lookup"]').click();

    // Wait for the search modal to appear
    await page.waitForSelector(".search-modal", { timeout: 10_000 });

    // Enter the AP URL in the search input
    const input = page.locator(".search-modal-input");
    await input.fill(noteUri);

    // Submit the form (press Enter) to trigger resolve
    await input.press("Enter");

    // The SearchModal should auto-navigate to /notes/{id} when a single status is resolved
    await page.waitForURL(`**/notes/${noteId}`, { timeout: 15_000 });

    // Verify the note content is displayed
    const content = await page.textContent(".note-card");
    expect(content).toContain("Resolve test note unique_resolve_e2e");
  });

  test("resolve local note by AP URL via search page", async ({ page }) => {
    await loginAsAdmin(page);

    // Create a note
    const note = await createNote(page, "Search page resolve test e2e_page_resolve");

    // Go to search page and search for the note content
    await page.goto("/search");
    await page.waitForSelector(".search-form", { timeout: 10_000 });

    await page.fill(".search-input", "e2e_page_resolve");
    await page.click('.search-form .btn[type="submit"]');

    // Wait for results
    await page.waitForSelector(".note-card", { timeout: 15_000 });
    const content = await page.textContent(".note-card");
    expect(content).toContain("e2e_page_resolve");
  });
});
