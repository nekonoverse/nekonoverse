import { test, expect } from "@playwright/test";
import { loginAsAdmin, createNote } from "./helpers";

test.describe("Profile Page", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("own profile page loads", async ({ page }) => {
    await page.goto("/@admin");
    await expect(page.locator(".profile-info")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('button:has-text("Edit Profile")')).toBeVisible();
  });

  test("shows user posts on profile", async ({ page }) => {
    // Create a note to ensure there's at least one
    await createNote(page, `Profile test ${Date.now()}`);

    await page.goto("/@admin");
    await expect(page.locator(".profile-posts")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(".profile-posts .note-card").first()).toBeVisible();
  });

  test("shows follow counts", async ({ page }) => {
    await page.goto("/@admin");
    await expect(page.locator(".profile-follow-counts")).toBeVisible({ timeout: 10_000 });
  });

  test("profile field input keeps focus while typing", async ({ page }) => {
    await page.goto("/@admin");
    await expect(page.locator('button:has-text("Edit Profile")')).toBeVisible({ timeout: 10_000 });
    await page.click('button:has-text("Edit Profile")');

    // Add a field
    await page.click('button:has-text("Add Field")');
    await expect(page.locator(".profile-edit-field-row")).toBeVisible({ timeout: 5_000 });

    // Type multiple characters into the label input and verify focus is retained
    const labelInput = page.locator(".profile-edit-field-row .profile-edit-field-input").first();
    await labelInput.click();
    await labelInput.pressSequentially("test label", { delay: 50 });
    await expect(labelInput).toBeFocused();
    await expect(labelInput).toHaveValue("test label");
  });
});
