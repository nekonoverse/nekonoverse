import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

/**
 * Profile editing e2e tests.
 *
 * Verifies that each profile field can be edited, saved, displayed on the
 * profile page, and correctly pre-filled when re-entering edit mode.
 */
test.describe("Profile Editing", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("edit display name, save, verify display and re-edit", async ({ page }) => {
    const name = `TestName${Date.now()}`;

    await page.goto("/@admin");
    await expect(page.locator(".profile-info")).toBeVisible({ timeout: 10_000 });

    // Enter edit mode
    await page.click('button:has-text("Edit Profile")');
    const nameInput = page.locator("input.profile-edit-input[type='text']").first();
    await expect(nameInput).toBeVisible({ timeout: 5_000 });

    // Edit display name
    await nameInput.fill(name);

    // Save
    const saveResponsePromise = page.waitForResponse(
      (resp) => resp.url().includes("/update_credentials") && resp.status() === 200,
      { timeout: 10_000 },
    );
    await page.click('button:has-text("Save")');
    await saveResponsePromise;

    // Verify display name shown on profile
    await expect(page.locator(".profile-display-name")).toContainText(name, { timeout: 5_000 });

    // Re-enter edit mode and verify form is pre-filled
    await page.click('button:has-text("Edit Profile")');
    await expect(nameInput).toBeVisible({ timeout: 5_000 });
    await expect(nameInput).toHaveValue(name);
  });

  test("edit bio, save, verify display and re-edit", async ({ page }) => {
    const bio = `Test bio ${Date.now()}`;

    await page.goto("/@admin");
    await expect(page.locator(".profile-info")).toBeVisible({ timeout: 10_000 });
    await page.click('button:has-text("Edit Profile")');

    const bioTextarea = page.locator("textarea.profile-edit-textarea");
    await expect(bioTextarea).toBeVisible({ timeout: 5_000 });

    // Edit bio
    await bioTextarea.fill(bio);

    // Save
    const saveResponsePromise = page.waitForResponse(
      (resp) => resp.url().includes("/update_credentials") && resp.status() === 200,
      { timeout: 10_000 },
    );
    await page.click('button:has-text("Save")');
    await saveResponsePromise;

    // Verify bio displayed on profile
    await expect(page.locator(".profile-bio")).toContainText(bio, { timeout: 5_000 });

    // Re-enter edit mode and verify form is pre-filled
    await page.click('button:has-text("Edit Profile")');
    await expect(bioTextarea).toBeVisible({ timeout: 5_000 });
    await expect(bioTextarea).toHaveValue(bio);
  });

  test("edit birthday, save, verify and re-edit", async ({ page }) => {
    const birthday = "2000-06-15";

    await page.goto("/@admin");
    await expect(page.locator(".profile-info")).toBeVisible({ timeout: 10_000 });
    await page.click('button:has-text("Edit Profile")');

    const birthdayInput = page.locator("input.profile-edit-input[type='date']");
    await expect(birthdayInput).toBeVisible({ timeout: 5_000 });

    // Edit birthday
    await birthdayInput.fill(birthday);

    // Save
    const saveResponsePromise = page.waitForResponse(
      (resp) => resp.url().includes("/update_credentials") && resp.status() === 200,
      { timeout: 10_000 },
    );
    await page.click('button:has-text("Save")');
    await saveResponsePromise;

    // Re-enter edit mode and verify form is pre-filled
    await page.click('button:has-text("Edit Profile")');
    await expect(birthdayInput).toBeVisible({ timeout: 5_000 });
    await expect(birthdayInput).toHaveValue(birthday);
  });

  test("edit custom fields, save, verify display and re-edit", async ({ page }) => {
    const fieldLabel = `Label${Date.now()}`;
    const fieldValue = `Value${Date.now()}`;

    await page.goto("/@admin");
    await expect(page.locator(".profile-info")).toBeVisible({ timeout: 10_000 });
    await page.click('button:has-text("Edit Profile")');

    // Remove any existing fields first
    while (await page.locator('button:has-text("Remove")').count() > 0) {
      await page.locator('button:has-text("Remove")').first().click();
    }

    // Add a new field
    await page.click('button:has-text("Add Field")');
    await expect(page.locator(".profile-edit-field-row")).toBeVisible({ timeout: 5_000 });

    // Fill field label and value
    const fieldInputs = page.locator(".profile-edit-field-row .profile-edit-field-input");
    await fieldInputs.nth(0).fill(fieldLabel);
    await fieldInputs.nth(1).fill(fieldValue);

    // Save
    const saveResponsePromise = page.waitForResponse(
      (resp) => resp.url().includes("/update_credentials") && resp.status() === 200,
      { timeout: 10_000 },
    );
    await page.click('button:has-text("Save")');
    await saveResponsePromise;

    // Verify field displayed on profile
    await expect(page.locator(".profile-fields")).toContainText(fieldLabel, { timeout: 5_000 });
    await expect(page.locator(".profile-fields")).toContainText(fieldValue);

    // Re-enter edit mode and verify fields pre-filled
    await page.click('button:has-text("Edit Profile")');
    await expect(page.locator(".profile-edit-field-row")).toBeVisible({ timeout: 5_000 });
    const reFieldInputs = page.locator(".profile-edit-field-row .profile-edit-field-input");
    await expect(reFieldInputs.nth(0)).toHaveValue(fieldLabel);
    await expect(reFieldInputs.nth(1)).toHaveValue(fieldValue);
  });

  test("edit checkboxes (is_cat, is_bot), save and re-edit", async ({ page }) => {
    await page.goto("/@admin");
    await expect(page.locator(".profile-info")).toBeVisible({ timeout: 10_000 });
    await page.click('button:has-text("Edit Profile")');

    const catCheckbox = page.locator(".profile-edit-checkboxes input[type='checkbox']").nth(0);
    const botCheckbox = page.locator(".profile-edit-checkboxes input[type='checkbox']").nth(1);
    await expect(catCheckbox).toBeVisible({ timeout: 5_000 });

    // Get current state and toggle
    const wasCat = await catCheckbox.isChecked();
    const wasBot = await botCheckbox.isChecked();

    if (wasCat) await catCheckbox.uncheck(); else await catCheckbox.check();
    if (wasBot) await botCheckbox.uncheck(); else await botCheckbox.check();

    // Save
    const saveResponsePromise = page.waitForResponse(
      (resp) => resp.url().includes("/update_credentials") && resp.status() === 200,
      { timeout: 10_000 },
    );
    await page.click('button:has-text("Save")');
    await saveResponsePromise;

    // Re-enter edit mode and verify checkboxes reflect saved state
    await page.click('button:has-text("Edit Profile")');
    await expect(catCheckbox).toBeVisible({ timeout: 5_000 });

    if (wasCat) {
      await expect(catCheckbox).not.toBeChecked();
    } else {
      await expect(catCheckbox).toBeChecked();
    }
    if (wasBot) {
      await expect(botCheckbox).not.toBeChecked();
    } else {
      await expect(botCheckbox).toBeChecked();
    }

    // Restore original state
    if (wasCat) await catCheckbox.check(); else await catCheckbox.uncheck();
    if (wasBot) await botCheckbox.check(); else await botCheckbox.uncheck();
    const restorePromise = page.waitForResponse(
      (resp) => resp.url().includes("/update_credentials") && resp.status() === 200,
      { timeout: 10_000 },
    );
    await page.click('button:has-text("Save")');
    await restorePromise;
  });

  test("all fields persist together after save", async ({ page }) => {
    const name = `AllFields${Date.now()}`;
    const bio = `Combined test bio ${Date.now()}`;
    const birthday = "1995-12-25";
    const fieldLabel = `CombLabel${Date.now()}`;
    const fieldValue = `CombValue${Date.now()}`;

    await page.goto("/@admin");
    await expect(page.locator(".profile-info")).toBeVisible({ timeout: 10_000 });
    await page.click('button:has-text("Edit Profile")');

    // Fill all fields
    const nameInput = page.locator("input.profile-edit-input[type='text']").first();
    await nameInput.fill(name);

    const bioTextarea = page.locator("textarea.profile-edit-textarea");
    await bioTextarea.fill(bio);

    const birthdayInput = page.locator("input.profile-edit-input[type='date']");
    await birthdayInput.fill(birthday);

    // Remove existing fields and add new one
    while (await page.locator('button:has-text("Remove")').count() > 0) {
      await page.locator('button:has-text("Remove")').first().click();
    }
    await page.click('button:has-text("Add Field")');
    const fieldInputs = page.locator(".profile-edit-field-row .profile-edit-field-input");
    await fieldInputs.nth(0).fill(fieldLabel);
    await fieldInputs.nth(1).fill(fieldValue);

    // Save
    const saveResponsePromise = page.waitForResponse(
      (resp) => resp.url().includes("/update_credentials") && resp.status() === 200,
      { timeout: 10_000 },
    );
    await page.click('button:has-text("Save")');
    await saveResponsePromise;

    // Verify all displayed
    await expect(page.locator(".profile-display-name")).toContainText(name, { timeout: 5_000 });
    await expect(page.locator(".profile-bio")).toContainText(bio);
    await expect(page.locator(".profile-fields")).toContainText(fieldLabel);
    await expect(page.locator(".profile-fields")).toContainText(fieldValue);

    // Re-enter edit and verify all pre-filled
    await page.click('button:has-text("Edit Profile")');
    await expect(nameInput).toHaveValue(name, { timeout: 5_000 });
    await expect(bioTextarea).toHaveValue(bio);
    await expect(birthdayInput).toHaveValue(birthday);

    const reFieldInputs = page.locator(".profile-edit-field-row .profile-edit-field-input");
    await expect(reFieldInputs.nth(0)).toHaveValue(fieldLabel);
    await expect(reFieldInputs.nth(1)).toHaveValue(fieldValue);
  });
});
