import { test, expect } from "@playwright/test";
import { loginAsAdmin, createNote } from "./helpers";

/**
 * Helper: press a key once then wait for the expected card to receive focus.
 * Key press and assertion are separated so retries don't send duplicate keys.
 */
async function pressAndWaitFocus(
  page: import("@playwright/test").Page,
  key: string,
  expectedIndex: number,
) {
  await page.keyboard.press(key);
  await expect(
    page.locator(".note-card").nth(expectedIndex),
  ).toHaveClass(/keyboard-focused/, { timeout: 5_000 });
}

/**
 * Helper: assert that the focused card's top is not hidden behind the navbar.
 * Uses toPass() to tolerate scroll animation delay.
 */
async function assertCardNotBehindNavbar(
  page: import("@playwright/test").Page,
  navbarHeight: number,
) {
  const focused = page.locator(".note-card.keyboard-focused");
  await expect(async () => {
    const top = await focused.evaluate((el) => el.getBoundingClientRect().top);
    expect(top).toBeGreaterThanOrEqual(navbarHeight - 2);
  }).toPass({ timeout: 5_000 });
}

test.describe("Keyboard navigation (j/k/g)", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);

    // Create notes to ensure enough content for scrolling
    for (let i = 0; i < 8; i++) {
      await createNote(page, `KBNav test note ${Date.now()}-${i}`);
    }

    // Navigate to public timeline and wait for notes to render
    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 15_000 });
  });

  test("j key moves focus down and cards stay visible below navbar", async ({
    page,
  }) => {
    test.setTimeout(45_000);

    const navbarHeight = await page
      .locator(".navbar")
      .evaluate((el) => el.getBoundingClientRect().height);

    const cardCount = await page.locator(".note-card").count();
    const stepsToTest = Math.min(cardCount, 5);

    for (let i = 0; i < stepsToTest; i++) {
      await pressAndWaitFocus(page, "j", i);
      await assertCardNotBehindNavbar(page, navbarHeight);
    }
  });

  test("k key moves focus up without card hidden behind navbar", async ({
    page,
  }) => {
    test.setTimeout(45_000);

    const navbarHeight = await page
      .locator(".navbar")
      .evaluate((el) => el.getBoundingClientRect().height);

    const cardCount = await page.locator(".note-card").count();
    const stepsDown = Math.min(cardCount, 5);

    // Move down first
    for (let i = 0; i < stepsDown; i++) {
      await pressAndWaitFocus(page, "j", i);
    }

    // Now move back up
    for (let i = 0; i < stepsDown - 1; i++) {
      const expectedIdx = stepsDown - 2 - i;
      await pressAndWaitFocus(page, "k", expectedIdx);
      await assertCardNotBehindNavbar(page, navbarHeight);
    }
  });

  test("rapid j presses all apply correctly", async ({ page }) => {
    test.setTimeout(45_000);
    const cardCount = await page.locator(".note-card").count();
    const presses = Math.min(cardCount, 6);

    for (let i = 0; i < presses; i++) {
      await pressAndWaitFocus(page, "j", i);
    }

    // Should have exactly one focused card at the expected position
    const focused = page.locator(".note-card.keyboard-focused");
    await expect(focused).toHaveCount(1, { timeout: 5_000 });
    await expect(
      page.locator(".note-card").nth(presses - 1),
    ).toHaveClass(/keyboard-focused/, { timeout: 5_000 });
  });

  test("g key scrolls to top and clears focus", async ({ page }) => {
    test.setTimeout(45_000);

    // Move down a few notes
    for (let i = 0; i < 5; i++) {
      await pressAndWaitFocus(page, "j", i);
    }

    await expect(page.locator(".note-card.keyboard-focused")).toHaveCount(1, {
      timeout: 5_000,
    });

    // Press g
    await page.keyboard.press("g");

    // Should scroll to top (tolerate animation delay)
    await expect(async () => {
      const scrollY = await page.evaluate(() => window.scrollY);
      expect(scrollY).toBe(0);
    }).toPass({ timeout: 5_000 });

    // No focused cards
    await expect(page.locator(".note-card.keyboard-focused")).toHaveCount(0);
  });
});
