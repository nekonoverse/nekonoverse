import { test, expect } from "@playwright/test";
import { loginAsAdmin, registerAndLogin, getActorId } from "./helpers";

const baseURL = process.env.E2E_BASE_URL || "http://localhost:3080";

/**
 * Set locked mode via update_credentials API.
 */
async function setLocked(page: import("@playwright/test").Page, locked: boolean) {
  const resp = await page.request.patch("/api/v1/accounts/update_credentials", {
    multipart: { locked: locked.toString() },
  });
  expect(resp.status()).toBe(200);
}

test.describe("Follow Requests", () => {
  test.afterEach(async ({ page }) => {
    // page is still logged in as admin (follower used separate context)
    await setLocked(page, false);
  });

  test("follow request appears and can be accepted", async ({ browser, page }) => {
    await loginAsAdmin(page);
    // Clear any leftover state: unlock (auto-approves pending), then re-lock
    await setLocked(page, false);
    await setLocked(page, true);
    const adminId = await getActorId(page, "admin");

    // Create follower in a separate browser context and send follow request
    const follower = await registerAndLogin(browser, `follower_${Date.now()}`, "testpassword123", baseURL);
    const followResp = await follower.page.request.post(`/api/v1/accounts/${adminId}/follow`);
    expect(followResp.ok()).toBeTruthy();

    // Check follow request page as admin
    await page.goto("/follow-requests");
    await expect(page.locator(".follow-request-item")).toBeVisible({ timeout: 10_000 });

    // Accept the follow request
    const acceptResponsePromise = page.waitForResponse(
      (resp) => resp.url().includes("/authorize") && resp.status() === 200,
      { timeout: 10_000 },
    );
    await page.locator(".follow-request-accept").first().click();
    await acceptResponsePromise;

    // Verify the request disappeared
    await expect(page.locator(".follow-request-item")).toHaveCount(0, { timeout: 5_000 });
    await follower.context.close();
  });

  test("follow request can be rejected", async ({ browser, page }) => {
    await loginAsAdmin(page);
    await setLocked(page, false);
    await setLocked(page, true);
    const adminId = await getActorId(page, "admin");

    const follower = await registerAndLogin(browser, `follower_${Date.now()}`, "testpassword123", baseURL);
    const followResp = await follower.page.request.post(`/api/v1/accounts/${adminId}/follow`);
    expect(followResp.ok()).toBeTruthy();

    await page.goto("/follow-requests");
    await expect(page.locator(".follow-request-item")).toBeVisible({ timeout: 10_000 });

    // Reject the follow request
    const rejectResponsePromise = page.waitForResponse(
      (resp) => resp.url().includes("/reject") && resp.status() === 200,
      { timeout: 10_000 },
    );
    await page.locator(".follow-request-reject").first().click();
    await rejectResponsePromise;

    await expect(page.locator(".follow-request-item")).toHaveCount(0, { timeout: 5_000 });
    await follower.context.close();
  });

  test("empty state shown when no requests", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/follow-requests");
    await expect(page.locator(".empty")).toBeVisible({ timeout: 10_000 });
  });

  test("confirmation modal appears when disabling locked mode", async ({ page }) => {
    await loginAsAdmin(page);
    await setLocked(page, true);

    // Go to profile and enter edit mode
    await page.goto("/@admin");
    await expect(page.locator(".profile-info")).toBeVisible({ timeout: 10_000 });
    await page.click('button:has-text("Edit Profile")');

    // Find the locked checkbox (3rd checkbox in the group)
    const lockedCheckbox = page.locator(".profile-edit-checkboxes input[type='checkbox']").nth(2);
    await expect(lockedCheckbox).toBeVisible({ timeout: 5_000 });
    await expect(lockedCheckbox).toBeChecked();

    // Uncheck locked
    await lockedCheckbox.uncheck();

    // Click Save - should show modal instead of saving
    await page.click('button:has-text("Save")');

    // Modal should appear
    await expect(page.locator(".modal-overlay")).toBeVisible({ timeout: 5_000 });

    // Cancel - should close modal without saving
    await page.locator(".modal-content .btn:not(.btn-danger)").click();
    await expect(page.locator(".modal-overlay")).toHaveCount(0, { timeout: 3_000 });

    // Still in edit mode
    await expect(lockedCheckbox).toBeVisible();
  });

  test("confirming unlock modal saves and auto-approves pending requests", async ({ browser, page }) => {
    await loginAsAdmin(page);
    await setLocked(page, false);
    await setLocked(page, true);
    const adminId = await getActorId(page, "admin");

    // Create follower and send follow request
    const follower = await registerAndLogin(browser, `follower_${Date.now()}`, "testpassword123", baseURL);
    const followResp = await follower.page.request.post(`/api/v1/accounts/${adminId}/follow`);
    expect(followResp.ok()).toBeTruthy();
    await follower.context.close();

    // Verify request exists
    const reqResp = await page.request.get("/api/v1/follow_requests");
    const requests = await reqResp.json();
    expect(requests.length).toBeGreaterThan(0);

    // Go to profile, enter edit mode, uncheck locked, save
    await page.goto("/@admin");
    await expect(page.locator(".profile-info")).toBeVisible({ timeout: 10_000 });
    await page.click('button:has-text("Edit Profile")');

    const lockedCheckbox = page.locator(".profile-edit-checkboxes input[type='checkbox']").nth(2);
    await expect(lockedCheckbox).toBeChecked({ timeout: 5_000 });
    await lockedCheckbox.uncheck();

    await page.click('button:has-text("Save")');

    // Modal should appear - confirm this time
    await expect(page.locator(".modal-overlay")).toBeVisible({ timeout: 5_000 });

    const saveResponsePromise = page.waitForResponse(
      (resp) => resp.url().includes("/update_credentials") && resp.status() === 200,
      { timeout: 10_000 },
    );
    await page.locator(".modal-content button.btn-danger").click();
    await saveResponsePromise;

    // Should exit edit mode
    await expect(page.locator(".profile-edit-checkboxes")).toHaveCount(0, { timeout: 5_000 });

    // Verify follow requests are now empty (auto-approved)
    const reqResp2 = await page.request.get("/api/v1/follow_requests");
    const requests2 = await reqResp2.json();
    expect(requests2.length).toBe(0);
  });
});
