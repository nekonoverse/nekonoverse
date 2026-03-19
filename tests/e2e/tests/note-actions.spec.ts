import { test, expect } from "@playwright/test";
import { loginAsAdmin, createNote } from "./helpers";

test.describe("Note Actions", () => {
  test("reblog button toggles boost state", async ({ page }) => {
    await loginAsAdmin(page);
    const uid = Date.now();
    const note = await createNote(page, `reblog-test-${uid}`);

    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    // 該当ノートのブーストボタンを見つける
    const noteCard = page
      .locator(`.note-card`)
      .filter({ hasText: `reblog-test-${uid}` })
      .first();
    const boostBtn = noteCard.locator(".note-boost-btn");
    await expect(boostBtn).toBeEnabled({ timeout: 5_000 });
    // Ensure not boosted before clicking
    await expect(boostBtn).not.toHaveClass(/boosted/, { timeout: 5_000 });
    // Scroll into view and let Firefox settle before clicking
    await boostBtn.scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);

    // Click and verify the API call actually fires (Firefox sometimes swallows clicks)
    await Promise.all([
      page.waitForResponse(
        (resp) => resp.url().includes("/reblog") && resp.status() === 200,
        { timeout: 15_000 },
      ),
      boostBtn.click(),
    ]);

    // Wait for boosted class (API round-trip)
    await expect(boostBtn).toHaveClass(/boosted/, { timeout: 10_000 });

    // Wait for button to become enabled and stable before un-boosting
    await expect(boostBtn).toBeEnabled({ timeout: 5_000 });
    // Small delay for Firefox to settle DOM state after re-render
    await page.waitForTimeout(500);

    await Promise.all([
      page.waitForResponse(
        (resp) => resp.url().includes("/unreblog") && resp.status() === 200,
        { timeout: 15_000 },
      ),
      boostBtn.click(),
    ]);
    await expect(boostBtn).not.toHaveClass(/boosted/, { timeout: 10_000 });
  });

  test("bookmark button toggles bookmarked state", async ({ page }) => {
    await loginAsAdmin(page);
    const uid = Date.now();
    const note = await createNote(page, `bookmark-action-${uid}`);

    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const noteCard = page
      .locator(`.note-card`)
      .filter({ hasText: `bookmark-action-${uid}` })
      .first();
    const bookmarkBtn = noteCard.locator(".note-bookmark-btn");
    await bookmarkBtn.click();

    await expect(bookmarkBtn).toHaveClass(/bookmarked/, { timeout: 5_000 });

    // 解除
    await bookmarkBtn.click();
    await expect(bookmarkBtn).not.toHaveClass(/bookmarked/, { timeout: 5_000 });
  });

  test("delete note removes it from timeline", async ({ page }) => {
    await loginAsAdmin(page);
    const uid = Date.now();
    const note = await createNote(page, `delete-test-${uid}`);

    // APIで削除してからタイムラインで確認する方式(UIのconfirmダイアログの不安定さを回避)
    const delResp = await page.request.delete(`/api/v1/statuses/${note.id}`);
    expect(delResp.ok()).toBeTruthy();

    await page.goto("/");
    await page.waitForSelector(".note-card, .empty", { timeout: 10_000 });

    // 削除済みノートがタイムラインに表示されないこと
    await expect(
      page.locator(`.note-card:has-text("delete-test-${uid}")`),
    ).toHaveCount(0, { timeout: 5_000 });
  });
});
