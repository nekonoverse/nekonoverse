import { test, expect } from "@playwright/test";
import { loginAsAdmin, createNote } from "./helpers";

test.describe("Reply Visibility", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("reply to followers-only note defaults to followers", async ({ page }) => {
    const uid = Date.now();
    const note = await createNote(page, `fonly-vis-${uid}`, "followers");

    await page.goto(`/notes/${note.id}`);
    await expect(page.locator(".thread-view")).toBeVisible({ timeout: 10_000 });

    // コンポーザーの公開範囲アイコンがロック (followers) であること
    const visIcon = page.locator(".thread-reply-composer .composer-vis-icon");
    await expect(visIcon).toBeVisible({ timeout: 5_000 });
    await expect(visIcon).toHaveText("\u{1F512}");
  });

  test("warning appears when widening reply visibility", async ({ page }) => {
    const uid = Date.now();
    const note = await createNote(page, `warn-vis-${uid}`, "followers");

    await page.goto(`/notes/${note.id}`);
    await expect(page.locator(".thread-view")).toBeVisible({ timeout: 10_000 });

    const composer = page.locator(".thread-reply-composer");

    // 初期状態では警告なし
    await expect(composer.locator(".composer-visibility-warning")).not.toBeVisible();

    // 公開範囲ドロップダウンを開いて public を選択
    await composer.locator(".composer-vis-toggle").click();
    await composer.locator(".composer-vis-item").first().click();

    // 警告バナーが表示されること
    await expect(composer.locator(".composer-visibility-warning")).toBeVisible({ timeout: 3_000 });
  });

  test("reply to unlisted note defaults to unlisted", async ({ page }) => {
    const uid = Date.now();
    const note = await createNote(page, `unlisted-vis-${uid}`, "unlisted");

    await page.goto(`/notes/${note.id}`);
    await expect(page.locator(".thread-view")).toBeVisible({ timeout: 10_000 });

    const visIcon = page.locator(".thread-reply-composer .composer-vis-icon");
    await expect(visIcon).toBeVisible({ timeout: 5_000 });
    await expect(visIcon).toHaveText("\u{1F513}");
  });

  test("reply to public note stays public with no warning", async ({ page }) => {
    const uid = Date.now();
    const note = await createNote(page, `public-vis-${uid}`);

    await page.goto(`/notes/${note.id}`);
    await expect(page.locator(".thread-view")).toBeVisible({ timeout: 10_000 });

    const composer = page.locator(".thread-reply-composer");
    const visIcon = composer.locator(".composer-vis-icon");
    await expect(visIcon).toBeVisible({ timeout: 5_000 });
    await expect(visIcon).toHaveText("\u{1F310}");

    // 警告なし
    await expect(composer.locator(".composer-visibility-warning")).not.toBeVisible();
  });

  test("reply to direct note defaults to direct", async ({ page }) => {
    const uid = Date.now();
    const note = await createNote(page, `direct-vis-${uid}`, "direct");

    await page.goto(`/notes/${note.id}`);
    await expect(page.locator(".thread-view")).toBeVisible({ timeout: 10_000 });

    const visIcon = page.locator(".thread-reply-composer .composer-vis-icon");
    await expect(visIcon).toBeVisible({ timeout: 5_000 });
    await expect(visIcon).toHaveText("\u2709\uFE0F");
  });

  test("reply via modal inherits followers visibility", async ({ page }) => {
    const uid = Date.now();
    const note = await createNote(page, `modal-vis-${uid}`, "followers");

    // ホームタイムラインで自分の followers-only ノートを見つけてリプライ
    await page.goto("/?tl=home");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const noteCard = page
      .locator(".note-card")
      .filter({ hasText: `modal-vis-${uid}` })
      .first();
    await noteCard.locator(".note-reply-btn").click();

    // モーダルが開く
    await expect(page.locator(".compose-modal-content")).toBeVisible({ timeout: 5_000 });

    // 公開範囲がロック (followers) であること
    const visIcon = page.locator(".compose-modal-content .composer-vis-icon");
    await expect(visIcon).toHaveText("\u{1F512}");
  });
});
