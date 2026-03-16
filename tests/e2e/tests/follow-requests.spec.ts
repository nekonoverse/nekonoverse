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

/**
 * Clear all pending follow requests by approving them via API.
 */
async function clearPendingRequests(page: import("@playwright/test").Page) {
  const resp = await page.request.get("/api/v1/follow_requests");
  if (resp.ok()) {
    const requests = await resp.json();
    for (const req of requests) {
      await page.request.post(`/api/v1/follow_requests/${req.id}/authorize`);
    }
  }
}

test.describe("Follow Requests", () => {
  test.afterEach(async ({ page }) => {
    await clearPendingRequests(page);
    await setLocked(page, false);
  });

  test("follow request appears and can be accepted", async ({ browser, page }) => {
    await loginAsAdmin(page);
    await clearPendingRequests(page);
    await setLocked(page, true);
    const adminId = await getActorId(page, "admin");

    const follower = await registerAndLogin(browser, `follower_${Date.now()}`, "testpassword123", baseURL);
    const followResp = await follower.page.request.post(`/api/v1/accounts/${adminId}/follow`);
    expect(followResp.ok()).toBeTruthy();

    // Avatar badge should appear indicating pending follow request
    // Wait for the follow_requests API fetch (triggered on SSE connect) to complete
    const frResponsePromise = page.waitForResponse(
      (resp) => resp.url().includes("/api/v1/follow_requests") && resp.status() === 200,
      { timeout: 15_000 },
    );
    await page.goto("/");
    await frResponsePromise;
    await expect(page.locator(".navbar-avatar-badge")).toBeVisible({ timeout: 5_000 });

    // Dropdown should show follow request count
    await page.locator(".navbar-avatar-wrap").click();
    await expect(page.locator(".navbar-dropdown-badge")).toBeVisible({ timeout: 5_000 });
    await page.locator(".navbar-avatar-wrap").click();

    // Check follow request page as admin
    await page.goto("/follow-requests");
    const item = page.locator(".follow-request-item").first();
    await expect(item).toBeVisible({ timeout: 10_000 });

    // Accept the follow request
    const acceptResponsePromise = page.waitForResponse(
      (resp) => resp.url().includes("/authorize") && resp.status() === 200,
      { timeout: 10_000 },
    );
    await item.locator(".follow-request-accept").click();
    await acceptResponsePromise;

    // Verify via API that no pending requests remain
    const reqResp = await page.request.get("/api/v1/follow_requests");
    const remaining = await reqResp.json();
    expect(remaining.length).toBe(0);

    // Avatar badge should disappear after accepting all requests
    await expect(page.locator(".navbar-avatar-badge")).not.toBeVisible({ timeout: 5_000 });
    await follower.context.close();
  });

  test("follow request can be rejected", async ({ browser, page }) => {
    await loginAsAdmin(page);
    await clearPendingRequests(page);
    await setLocked(page, true);
    const adminId = await getActorId(page, "admin");

    const follower = await registerAndLogin(browser, `follower_${Date.now()}`, "testpassword123", baseURL);
    const followResp = await follower.page.request.post(`/api/v1/accounts/${adminId}/follow`);
    expect(followResp.ok()).toBeTruthy();

    await page.goto("/follow-requests");
    const item = page.locator(".follow-request-item").first();
    await expect(item).toBeVisible({ timeout: 10_000 });

    // Reject the follow request
    const rejectResponsePromise = page.waitForResponse(
      (resp) => resp.url().includes("/reject") && resp.status() === 200,
      { timeout: 10_000 },
    );
    await item.locator(".follow-request-reject").click();
    await rejectResponsePromise;

    const reqResp = await page.request.get("/api/v1/follow_requests");
    const remaining = await reqResp.json();
    expect(remaining.length).toBe(0);
    await follower.context.close();
  });

  test("empty state shown when no requests", async ({ page }) => {
    await loginAsAdmin(page);
    await clearPendingRequests(page);
    await setLocked(page, false);
    await page.goto("/follow-requests");
    await expect(page.locator(".empty")).toBeVisible({ timeout: 10_000 });
  });

  test("confirmation modal appears when disabling locked mode", async ({ page }) => {
    await loginAsAdmin(page);
    await clearPendingRequests(page);
    await setLocked(page, true);

    await page.goto("/@admin");
    await expect(page.locator(".profile-info")).toBeVisible({ timeout: 10_000 });
    await page.click('button:has-text("Edit Profile")');

    const lockedCheckbox = page.locator(".profile-edit-checkboxes input[type='checkbox']").nth(2);
    await expect(lockedCheckbox).toBeVisible({ timeout: 5_000 });
    await expect(lockedCheckbox).toBeChecked();

    await lockedCheckbox.uncheck();
    await page.click('button:has-text("Save")');

    await expect(page.locator(".modal-overlay")).toBeVisible({ timeout: 5_000 });

    await page.locator(".modal-content .btn:not(.btn-danger)").click();
    await expect(page.locator(".modal-overlay")).toHaveCount(0, { timeout: 3_000 });

    await expect(lockedCheckbox).toBeVisible();
  });

  test("confirming unlock modal saves and auto-approves pending requests", async ({ browser, page }) => {
    await loginAsAdmin(page);
    await clearPendingRequests(page);
    await setLocked(page, true);
    const adminId = await getActorId(page, "admin");

    const follower = await registerAndLogin(browser, `follower_${Date.now()}`, "testpassword123", baseURL);
    const followResp = await follower.page.request.post(`/api/v1/accounts/${adminId}/follow`);
    expect(followResp.ok()).toBeTruthy();
    await follower.context.close();

    // Verify request exists
    const reqResp = await page.request.get("/api/v1/follow_requests");
    const requests = await reqResp.json();
    expect(requests.length).toBeGreaterThan(0);

    await page.goto("/@admin");
    await expect(page.locator(".profile-info")).toBeVisible({ timeout: 10_000 });
    await page.click('button:has-text("Edit Profile")');

    const lockedCheckbox = page.locator(".profile-edit-checkboxes input[type='checkbox']").nth(2);
    await expect(lockedCheckbox).toBeChecked({ timeout: 5_000 });
    await lockedCheckbox.uncheck();

    await page.click('button:has-text("Save")');

    await expect(page.locator(".modal-overlay")).toBeVisible({ timeout: 5_000 });

    const saveResponsePromise = page.waitForResponse(
      (resp) => resp.url().includes("/update_credentials") && resp.status() === 200,
      { timeout: 10_000 },
    );
    await page.locator(".modal-content button.btn-danger").click();
    await saveResponsePromise;

    await expect(page.locator(".profile-edit-checkboxes")).toHaveCount(0, { timeout: 5_000 });

    // Verify follow requests are now empty (auto-approved)
    const reqResp2 = await page.request.get("/api/v1/follow_requests");
    const requests2 = await reqResp2.json();
    expect(requests2.length).toBe(0);
  });
});
