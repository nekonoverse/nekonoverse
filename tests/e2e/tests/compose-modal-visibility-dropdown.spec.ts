import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test.describe("Compose Modal visibility dropdown", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await expect(page.locator("form.note-composer")).toBeVisible({
      timeout: 10_000,
    });
  });

  test("visibility dropdown is not clipped by modal overflow", async ({
    page,
  }) => {
    // Open compose modal with n key
    await page.keyboard.press("n");
    const modal = page.locator(".compose-modal-content");
    await expect(modal).toBeVisible({ timeout: 5_000 });

    // Click the ▲ visibility toggle button INSIDE the modal
    await modal.locator(".composer-vis-toggle").click();

    // The dropdown should be visible
    const dropdown = modal.locator(".composer-vis-dropdown");
    await expect(dropdown).toBeVisible({ timeout: 3_000 });

    // Verify the dropdown has all 4 visibility options
    const items = dropdown.locator(".composer-vis-item");
    await expect(items).toHaveCount(4);

    // Get the bounding box of the dropdown and the modal
    const dropdownBox = await dropdown.boundingBox();
    expect(dropdownBox, "dropdown should have a bounding box").toBeTruthy();

    const modalBox = await modal.boundingBox();
    expect(modalBox, "modal should have a bounding box").toBeTruthy();

    // The first item (Public) must be fully visible and clickable.
    // Bug: the modal-header covers the top of the dropdown, hiding "Public".
    const firstItem = items.first();
    await expect(firstItem).toBeVisible();

    // The first item must not be obscured by the modal header.
    const firstItemBox = await firstItem.boundingBox();
    expect(firstItemBox, "first item should have a bounding box").toBeTruthy();
    expect(
      firstItemBox!.y,
      "first dropdown item top should be at or below modal top " +
        `(item.y=${firstItemBox!.y}, modal.y=${modalBox!.y})`,
    ).toBeGreaterThanOrEqual(modalBox!.y);

    // Try clicking the first item — if obscured, modal-header intercepts
    await firstItem.click({ timeout: 5_000 });

    // After clicking, the dropdown should close
    await expect(dropdown).not.toBeVisible();
  });
});
