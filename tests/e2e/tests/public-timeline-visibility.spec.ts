import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

/**
 * Public timeline visibility e2e tests.
 *
 * Verifies that only `public` visibility notes appear on the public timeline
 * via both REST API and streaming (SSE). Notes with `unlisted`, `private`,
 * or `direct` visibility must NOT leak into the public timeline.
 */
test.describe("Public Timeline Visibility Filtering", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("unlisted note does NOT appear on public timeline via streaming", async ({
    page,
  }) => {
    // Navigate to public timeline (default view)
    await page.goto("/");
    await expect(page.locator(".timeline h2")).toBeVisible({ timeout: 10_000 });

    // Post a public note first as a control to prove streaming works
    const controlText = `public-control-${Date.now()}`;
    const controlResp = await page.request.post("/api/v1/statuses", {
      data: { content: controlText, visibility: "public" },
    });
    expect(controlResp.status()).toBe(201);

    // Wait for the public note to appear via streaming
    await expect(
      page.locator(".note-card").filter({ hasText: controlText }),
    ).toBeVisible({ timeout: 15_000 });

    // Now post an unlisted note — it should NOT appear on public timeline
    const unlistedText = `unlisted-leak-test-${Date.now()}`;
    const unlistedResp = await page.request.post("/api/v1/statuses", {
      data: { content: unlistedText, visibility: "unlisted" },
    });
    expect(unlistedResp.status()).toBe(201);

    // The unlisted note must NOT appear on the public timeline
    // Wait briefly for streaming, then assert absence
    await page.waitForTimeout(1000);
    await expect(
      page.locator(".note-card").filter({ hasText: unlistedText }),
    ).not.toBeVisible();

    // Switch to home timeline — the unlisted note SHOULD be there
    await page.goto("/?tl=home");
    await expect(
      page.locator(".note-card").filter({ hasText: unlistedText }),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("private (followers-only) note does NOT appear on public timeline via streaming", async ({
    page,
  }) => {
    // Navigate to public timeline
    await page.goto("/");
    await expect(page.locator(".timeline h2")).toBeVisible({ timeout: 10_000 });

    // Post a public note as control
    const controlText = `public-control2-${Date.now()}`;
    await page.request.post("/api/v1/statuses", {
      data: { content: controlText, visibility: "public" },
    });
    await expect(
      page.locator(".note-card").filter({ hasText: controlText }),
    ).toBeVisible({ timeout: 15_000 });

    // Post a followers-only note
    const privateText = `followers-leak-test-${Date.now()}`;
    const privateResp = await page.request.post("/api/v1/statuses", {
      data: { content: privateText, visibility: "followers" },
    });
    expect(privateResp.status()).toBe(201);

    // Must NOT appear on public timeline
    await page.waitForTimeout(1000);
    await expect(
      page.locator(".note-card").filter({ hasText: privateText }),
    ).not.toBeVisible();

    // But SHOULD appear on home timeline
    await page.goto("/?tl=home");
    await expect(
      page.locator(".note-card").filter({ hasText: privateText }),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("unlisted note does NOT appear on public timeline after page refresh", async ({
    page,
  }) => {
    // Create an unlisted note via API
    const unlistedText = `unlisted-refresh-test-${Date.now()}`;
    await page.request.post("/api/v1/statuses", {
      data: { content: unlistedText, visibility: "unlisted" },
    });

    // Load public timeline
    await page.goto("/");
    await expect(page.locator(".timeline h2")).toBeVisible({ timeout: 10_000 });

    // Wait for timeline to fully load (at least one note rendered)
    await expect(page.locator(".note-card").first()).toBeVisible({ timeout: 10_000 });

    // Unlisted note should NOT be on public timeline (REST API)
    await expect(
      page.locator(".note-card").filter({ hasText: unlistedText }),
    ).not.toBeVisible();

    // But should be on home timeline
    await page.goto("/?tl=home");
    await expect(
      page.locator(".note-card").filter({ hasText: unlistedText }),
    ).toBeVisible({ timeout: 10_000 });
  });
});
