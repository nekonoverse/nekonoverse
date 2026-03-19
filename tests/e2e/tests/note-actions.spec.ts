import { test, expect } from "@playwright/test";
import { loginAsAdmin, createNote } from "./helpers";

test.describe("Note Actions", () => {
  test("reblog button toggles boost state", async ({ page }) => {
    await loginAsAdmin(page);
    const uid = Date.now();
    const note = await createNote(page, `reblog-test-${uid}`);

    // --- Boost ---
    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const noteCard = page
      .locator(`.note-card`)
      .filter({ hasText: `reblog-test-${uid}` })
      .first();
    const boostBtn = noteCard.locator(".note-boost-btn");
    await expect(boostBtn).toBeEnabled({ timeout: 5_000 });
    await expect(boostBtn).not.toHaveClass(/boosted/, { timeout: 5_000 });
    await boostBtn.scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);

    await Promise.all([
      page.waitForResponse(
        (resp) => resp.url().includes("/reblog") && resp.status() === 200,
        { timeout: 15_000 },
      ),
      boostBtn.click(),
    ]);
    await expect(boostBtn).toHaveClass(/boosted/, { timeout: 10_000 });

    // --- Un-boost: reload page to get fresh DOM references (Firefox workaround) ---
    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const noteCard2 = page
      .locator(`.note-card`)
      .filter({ hasText: `reblog-test-${uid}` })
      .first();
    const boostBtn2 = noteCard2.locator(".note-boost-btn");
    await expect(boostBtn2).toBeEnabled({ timeout: 5_000 });
    await expect(boostBtn2).toHaveClass(/boosted/, { timeout: 5_000 });
    await boostBtn2.scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);

    await Promise.all([
      page.waitForResponse(
        (resp) => resp.url().includes("/unreblog") && resp.status() === 200,
        { timeout: 15_000 },
      ),
      boostBtn2.click(),
    ]);
    await expect(boostBtn2).not.toHaveClass(/boosted/, { timeout: 10_000 });
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
