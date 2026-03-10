import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

/**
 * Dispatch a synthetic touch swipe on the page.
 * startX/startY → endX/endY over `steps` intermediate moves.
 */
async function swipe(
  page: import("@playwright/test").Page,
  startX: number,
  startY: number,
  endX: number,
  endY: number,
  steps = 10,
) {
  await page.evaluate(
    ({ sx, sy, ex, ey, n }) => {
      const el = document.documentElement;
      const fire = (type: string, x: number, y: number) => {
        const touch = new Touch({
          identifier: 0,
          target: el,
          clientX: x,
          clientY: y,
        });
        el.dispatchEvent(
          new TouchEvent(type, {
            touches: type === "touchend" ? [] : [touch],
            changedTouches: [touch],
            bubbles: true,
          }),
        );
      };

      fire("touchstart", sx, sy);
      for (let i = 1; i <= n; i++) {
        const t = i / n;
        fire("touchmove", sx + (ex - sx) * t, sy + (ey - sy) * t);
      }
      fire("touchend", ex, ey);
    },
    { sx: startX, sy: startY, ex: endX, ey: endY, n: steps },
  );
}

test.describe("Swipe-back gesture", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("left-edge swipe beyond threshold navigates back", async ({ page }) => {
    // Navigate to profile so there's history to go back to
    await page.goto("/@admin");
    await expect(page.locator(".profile-info")).toBeVisible({ timeout: 10_000 });

    // Start swipe from left edge (x=5), drag 150px right (past 100px threshold)
    const midY = 400;
    await swipe(page, 5, midY, 155, midY);

    // Should navigate back to home
    await expect(page).toHaveURL("/", { timeout: 5_000 });
  });

  test("swipe below threshold does not navigate", async ({ page }) => {
    await page.goto("/@admin");
    await expect(page.locator(".profile-info")).toBeVisible({ timeout: 10_000 });

    // Swipe only 50px — below 100px threshold
    await swipe(page, 5, 400, 55, 400);

    // Should stay on profile page
    await expect(page).toHaveURL(/\/@admin/, { timeout: 2_000 });
  });

  test("indicator appears and follows swipe", async ({ page }) => {
    await page.goto("/@admin");
    await expect(page.locator(".profile-info")).toBeVisible({ timeout: 10_000 });

    // Start swipe and hold mid-gesture (dispatch events step by step)
    await page.evaluate(() => {
      const el = document.documentElement;
      const fire = (type: string, x: number, y: number) => {
        const touch = new Touch({ identifier: 0, target: el, clientX: x, clientY: y });
        el.dispatchEvent(
          new TouchEvent(type, {
            touches: type === "touchend" ? [] : [touch],
            changedTouches: [touch],
            bubbles: true,
          }),
        );
      };
      fire("touchstart", 5, 400);
      fire("touchmove", 30, 400);
      fire("touchmove", 60, 400);
    });

    // Indicator should be visible (below threshold — no ready class)
    const indicator = page.locator(".swipe-back-indicator");
    await expect(indicator).toBeVisible({ timeout: 2_000 });
    await expect(indicator).not.toHaveClass(/swipe-back-ready/);

    // Continue past threshold
    await page.evaluate(() => {
      const el = document.documentElement;
      const touch = new Touch({ identifier: 0, target: el, clientX: 120, clientY: 400 });
      el.dispatchEvent(
        new TouchEvent("touchmove", {
          touches: [touch],
          changedTouches: [touch],
          bubbles: true,
        }),
      );
    });

    // Should now have the ready class
    await expect(indicator).toHaveClass(/swipe-back-ready/, { timeout: 2_000 });

    // Cancel by sending touchend (cleanup)
    await page.evaluate(() => {
      const el = document.documentElement;
      const touch = new Touch({ identifier: 0, target: el, clientX: 120, clientY: 400 });
      el.dispatchEvent(
        new TouchEvent("touchend", {
          touches: [],
          changedTouches: [touch],
          bubbles: true,
        }),
      );
    });
  });

  test("vertical swipe does not activate indicator", async ({ page }) => {
    await page.goto("/@admin");
    await expect(page.locator(".profile-info")).toBeVisible({ timeout: 10_000 });

    // Swipe from left edge but mostly downward (vertical)
    await swipe(page, 5, 300, 15, 500);

    // Indicator should not be present
    await expect(page.locator(".swipe-back-indicator")).not.toBeVisible({ timeout: 1_000 });
  });

  test("swipe starting outside edge zone does not activate", async ({ page }) => {
    await page.goto("/@admin");
    await expect(page.locator(".profile-info")).toBeVisible({ timeout: 10_000 });

    // Start at x=80 — outside the 50px edge zone
    await swipe(page, 80, 400, 230, 400);

    // Should stay on profile, no navigation
    await expect(page).toHaveURL(/\/@admin/, { timeout: 2_000 });
  });

  test("swipe is blocked when modal overlay is present", async ({ page }) => {
    await page.goto("/@admin");
    await expect(page.locator(".profile-info")).toBeVisible({ timeout: 10_000 });

    // Inject a fake modal overlay
    await page.evaluate(() => {
      const overlay = document.createElement("div");
      overlay.className = "modal-overlay";
      document.body.appendChild(overlay);
    });

    // Swipe past threshold
    await swipe(page, 5, 400, 155, 400);

    // Should stay on profile (blocked by overlay)
    await expect(page).toHaveURL(/\/@admin/, { timeout: 2_000 });

    // Clean up
    await page.evaluate(() => {
      document.querySelector(".modal-overlay")?.remove();
    });
  });
});
