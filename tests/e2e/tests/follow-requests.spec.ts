import { test, expect } from "@playwright/test";
import { loginAsAdmin, registerUser } from "./helpers";

/**
 * Helper: login as a specific user via the API (not via UI form).
 */
async function loginAs(page: import("@playwright/test").Page, username: string, password: string) {
  const resp = await page.request.post("/api/v1/auth/login", {
    data: { username, password },
  });
  expect(resp.status()).toBe(200);
}

/**
 * Helper: set locked mode via update_credentials API.
 */
async function setLocked(page: import("@playwright/test").Page, locked: boolean) {
  const resp = await page.request.patch("/api/v1/accounts/update_credentials", {
    multipart: { locked: locked.toString() },
  });
  expect(resp.status()).toBe(200);
}

/**
 * Helper: get the current user's actor_id from verify_credentials.
 */
async function getMyActorId(page: import("@playwright/test").Page): Promise<string> {
  const resp = await page.request.get("/api/v1/accounts/verify_credentials");
  expect(resp.status()).toBe(200);
  const body = await resp.json();
  return body.id;
}

/**
 * Helper: send a follow request via API.
 */
async function followUser(page: import("@playwright/test").Page, targetActorId: string) {
  const resp = await page.request.post(`/api/v1/accounts/${targetActorId}/follow`);
  expect(resp.status()).toBe(200);
}

test.describe("Follow Requests", () => {
  const followerUsername = `follower_${Date.now()}`;
  const followerPassword = "testpassword123";

  test.beforeAll(async ({ browser }) => {
    // Register a follower user and enable locked mode on admin
    const page = await browser.newPage();
    await registerUser(page, followerUsername, followerPassword);
    await loginAsAdmin(page);
    await setLocked(page, true);
    await page.close();
  });

  test.afterAll(async ({ browser }) => {
    // Restore admin to unlocked mode
    const page = await browser.newPage();
    await loginAsAdmin(page);
    await setLocked(page, false);
    await page.close();
  });

  test("follow request appears and can be accepted", async ({ page }) => {
    // Login as admin, get actor_id
    await loginAsAdmin(page);
    const adminId = await getMyActorId(page);

    // Login as follower, send follow request to admin
    await loginAs(page, followerUsername, followerPassword);
    await followUser(page, adminId);

    // Login as admin again, check follow request page
    await loginAsAdmin(page);
    await page.goto("/follow-requests");
    await expect(page.locator(".follow-request-item")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(".follow-request-item")).toContainText(followerUsername);

    // Accept the follow request
    const acceptResponsePromise = page.waitForResponse(
      (resp) => resp.url().includes("/authorize") && resp.status() === 200,
      { timeout: 10_000 },
    );
    await page.locator(".follow-request-accept").first().click();
    await acceptResponsePromise;

    // Verify the request disappeared
    await expect(page.locator(".follow-request-item")).toHaveCount(0, { timeout: 5_000 });
  });

  test("follow request can be rejected", async ({ page }) => {
    // Login as admin, get actor_id
    await loginAsAdmin(page);
    const adminId = await getMyActorId(page);

    // Login as follower, send follow request
    await loginAs(page, followerUsername, followerPassword);
    await followUser(page, adminId);

    // Login as admin, check follow request page
    await loginAsAdmin(page);
    await page.goto("/follow-requests");
    await expect(page.locator(".follow-request-item")).toBeVisible({ timeout: 10_000 });

    // Reject the follow request
    const rejectResponsePromise = page.waitForResponse(
      (resp) => resp.url().includes("/reject") && resp.status() === 200,
      { timeout: 10_000 },
    );
    await page.locator(".follow-request-reject").first().click();
    await rejectResponsePromise;

    // Verify the request disappeared
    await expect(page.locator(".follow-request-item")).toHaveCount(0, { timeout: 5_000 });
  });

  test("empty state shown when no requests", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/follow-requests");
    await expect(page.locator(".empty")).toBeVisible({ timeout: 10_000 });
  });

  test("confirmation modal appears when disabling locked mode", async ({ page }) => {
    await loginAsAdmin(page);

    // Ensure locked mode is ON first
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
    await expect(page.locator(".modal-content")).toContainText("承認制");

    // Cancel - should close modal without saving
    await page.click('.modal-content button:has-text("キャンセル")');
    await expect(page.locator(".modal-overlay")).toHaveCount(0, { timeout: 3_000 });

    // Still in edit mode
    await expect(lockedCheckbox).toBeVisible();
  });

  test("confirming unlock modal saves and auto-approves pending requests", async ({ page }) => {
    // Login as admin, ensure locked, get actor_id
    await loginAsAdmin(page);
    await setLocked(page, true);
    const adminId = await getMyActorId(page);

    // Login as follower, send follow request
    await loginAs(page, followerUsername, followerPassword);
    await followUser(page, adminId);

    // Login as admin, verify request exists
    await loginAsAdmin(page);
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
    await page.locator('.modal-content button.btn-danger').click();
    await saveResponsePromise;

    // Should exit edit mode
    await expect(page.locator(".profile-edit-checkboxes")).toHaveCount(0, { timeout: 5_000 });

    // Verify follow requests are now empty (auto-approved)
    const reqResp2 = await page.request.get("/api/v1/follow_requests");
    const requests2 = await reqResp2.json();
    expect(requests2.length).toBe(0);
  });
});
