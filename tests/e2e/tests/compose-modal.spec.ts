import { test, expect } from "@playwright/test";
import { loginAsAdmin, createNote } from "./helpers";

test.describe("Compose Modal", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    // Wait for timeline to load
    await expect(page.locator("form.note-composer")).toBeVisible({
      timeout: 10_000,
    });
  });

  test("keyboard shortcuts are disabled while compose modal is open", async ({
    page,
  }) => {
    // Create a note so there's something to focus with j
    await createNote(page, `shortcut-test-${Date.now()}`);
    await page.goto("/");
    await expect(page.locator(".note-card").first()).toBeVisible({
      timeout: 10_000,
    });

    // Focus a note with j
    await page.keyboard.press("j");
    await expect(
      page.locator(".note-card.keyboard-focused"),
    ).toBeVisible({ timeout: 5_000 });

    // Open compose modal with n
    await page.keyboard.press("n");
    await expect(page.locator(".compose-modal-content")).toBeVisible({
      timeout: 5_000,
    });

    // Click outside the textarea but inside the modal (on the header)
    await page.locator(".modal-header h3").click();

    // Pressing q should NOT trigger quote action
    await page.keyboard.press("q");

    // The compose modal should still be open with no quote attached
    await expect(page.locator(".compose-modal-content")).toBeVisible();
    // No quote preview should appear
    await expect(
      page.locator(".composer-quote-preview"),
    ).not.toBeVisible();

    // Close modal with Escape
    await page.keyboard.press("Escape");
    await expect(
      page.locator(".compose-modal-content"),
    ).not.toBeVisible({ timeout: 5_000 });
  });

  test("n key opens compose modal", async ({ page }) => {
    await page.keyboard.press("n");
    await expect(page.locator(".compose-modal-content")).toBeVisible({
      timeout: 5_000,
    });
    // Close with Escape
    await page.keyboard.press("Escape");
    await expect(
      page.locator(".compose-modal-content"),
    ).not.toBeVisible({ timeout: 5_000 });
  });

  test("direct visibility is not available in default visibility settings", async ({
    page,
  }) => {
    await page.goto("/settings/posting");
    await page.waitForSelector(".settings-section", { timeout: 10_000 });

    // Check visibility selector options
    const options = await page.locator(".visibility-select option").allTextContents();
    const hasDirectOption = options.some((o) => o.includes("Direct") || o.includes("ダイレクト"));
    expect(hasDirectOption).toBe(false);
  });
});
