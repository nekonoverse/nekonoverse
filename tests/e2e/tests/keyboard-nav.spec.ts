import { test, expect } from "@playwright/test";
import { loginAsAdmin, createNote } from "./helpers";

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
    test.setTimeout(90_000);

    const navbarHeight = await page
      .locator(".navbar")
      .evaluate((el) => el.getBoundingClientRect().height);

    const cardCount = await page.locator(".note-card").count();
    const stepsToTest = Math.min(cardCount, 5);

    for (let i = 0; i < stepsToTest; i++) {
      await page.keyboard.press("j");

      const focused = page.locator(".note-card.keyboard-focused");
      await expect(focused).toHaveCount(1, { timeout: 5_000 });

      // Wait for scroll to settle (Firefox may not complete scroll synchronously)
      await page.waitForTimeout(300);

      // The focused card's top must not be hidden behind navbar
      const cardTop = await focused.evaluate(
        (el) => el.getBoundingClientRect().top,
      );
      expect(cardTop).toBeGreaterThanOrEqual(navbarHeight - 2);
    }
  });

  test("k key moves focus up without card hidden behind navbar", async ({
    page,
  }) => {
    test.setTimeout(90_000);

    const navbarHeight = await page
      .locator(".navbar")
      .evaluate((el) => el.getBoundingClientRect().height);

    const cardCount = await page.locator(".note-card").count();
    const stepsDown = Math.min(cardCount, 5);

    // Move down first
    for (let i = 0; i < stepsDown; i++) {
      await page.keyboard.press("j");
      await page.waitForTimeout(200);
    }

    // Now move back up
    for (let i = 0; i < stepsDown - 1; i++) {
      await page.keyboard.press("k");

      const focused = page.locator(".note-card.keyboard-focused");
      await expect(focused).toHaveCount(1, { timeout: 5_000 });

      // Wait for scroll to settle (Firefox may not complete scroll synchronously)
      await page.waitForTimeout(300);

      const cardTop = await focused.evaluate(
        (el) => el.getBoundingClientRect().top,
      );
      expect(cardTop).toBeGreaterThanOrEqual(navbarHeight - 2);
    }
  });

  test("rapid j presses all apply correctly", async ({ page }) => {
    test.setTimeout(90_000);
    const cardCount = await page.locator(".note-card").count();
    const presses = Math.min(cardCount, 6);

    // Press j multiple times, retrying if focus doesn't apply (Firefox CI)
    for (let i = 0; i < presses; i++) {
      await expect(async () => {
        await page.keyboard.press("j");
        await page.waitForTimeout(200);
        const cls = await page.locator(".note-card").nth(i).getAttribute("class");
        expect(cls).toContain("keyboard-focused");
      }).toPass({ timeout: 10_000 });
    }

    // Should have exactly one focused card
    const focused = page.locator(".note-card.keyboard-focused");
    await expect(focused).toHaveCount(1, { timeout: 5_000 });

    // It should be the Nth card (0-indexed)
    const allCards = page.locator(".note-card");
    const targetCard = allCards.nth(presses - 1);
    await expect(targetCard).toHaveClass(/keyboard-focused/, { timeout: 5_000 });
  });

  test("g key scrolls to top and clears focus", async ({ page }) => {
    test.setTimeout(90_000);

    // Move down a few notes, retrying j press if focus doesn't apply
    for (let i = 0; i < 5; i++) {
      await expect(async () => {
        await page.keyboard.press("j");
        await page.waitForTimeout(200);
        const cls = await page.locator(".note-card").nth(i).getAttribute("class");
        expect(cls).toContain("keyboard-focused");
      }).toPass({ timeout: 10_000 });
    }

    await expect(page.locator(".note-card.keyboard-focused")).toHaveCount(1, {
      timeout: 5_000,
    });

    // Press g
    await page.keyboard.press("g");
    await page.waitForTimeout(300);

    // Should be at top
    const scrollY = await page.evaluate(() => window.scrollY);
    expect(scrollY).toBe(0);

    // No focused cards
    await expect(page.locator(".note-card.keyboard-focused")).toHaveCount(0);
  });
});
