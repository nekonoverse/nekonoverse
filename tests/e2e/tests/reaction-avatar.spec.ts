import { test, expect } from "@playwright/test";
import {
  loginAsAdmin,
  createNote,
  registerAndLogin,
} from "./helpers";

test.describe("Reaction user avatar display", () => {
  test("reacted-by user avatars are visible", async ({ page, browser }) => {
    test.setTimeout(60_000);
    await loginAsAdmin(page);
    const uid = Date.now();
    const note = await createNote(page, `avatar-react-test-${uid}`);

    // Create a second user who will react
    const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3080";
    const { page: reactorPage, context: reactorCtx } =
      await registerAndLogin(browser, `avareact${uid}`, "AvaReact1234!", baseURL);

    // React with 👍
    const reactResp = await reactorPage.request.post(
      `/api/v1/statuses/${note.id}/react/%F0%9F%91%8D`,
    );
    expect(reactResp.ok()).toBeTruthy();
    await reactorCtx.close();

    // Reload admin's timeline and find the note
    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const noteCard = page
      .locator(".note-card")
      .filter({ hasText: `avatar-react-test-${uid}` })
      .first();

    // Verify reaction badge appears
    const badge = noteCard.locator(".reaction-badge").first();
    await expect(badge).toBeVisible({ timeout: 10_000 });

    // Hover over the reaction badge to trigger the reacted-by popover
    await badge.hover();

    // Wait for the reacted-by avatar to appear
    const avatar = page.locator(".reacted-by-avatar").first();
    await expect(avatar).toBeVisible({ timeout: 10_000 });

    // Verify avatar has a valid src (not empty, not undefined)
    const src = await avatar.getAttribute("src");
    expect(src).toBeTruthy();
    expect(src).not.toContain("undefined");

    // Screenshot for visual verification
    await page.screenshot({
      path: "test-results/reaction-avatar-visible.png",
      fullPage: false,
    });
  });
});
