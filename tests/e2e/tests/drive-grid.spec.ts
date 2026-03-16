import { test, expect } from "@playwright/test";
import { loginAsAdmin, png1x1 } from "./helpers";

/**
 * ドライブのグリッドレイアウトが正しく動作し、
 * 画像の重なり合いが発生しないことを検証する。
 */
test.describe("Drive grid layout", () => {
  test("drive page: images do not overlap in grid", async ({ page }) => {
    await loginAsAdmin(page);

    // 4枚の画像をアップロード
    const uid = Date.now();
    for (let i = 0; i < 4; i++) {
      const resp = await page.request.post("/api/v1/media", {
        multipart: {
          file: { name: `grid-test-${uid}-${i}.png`, mimeType: "image/png", buffer: png1x1() },
        },
      });
      expect(resp.ok()).toBeTruthy();
    }

    await page.goto("/drive");
    await page.waitForSelector(".drive-grid", { timeout: 10_000 });

    // アップロードした画像がすべて表示されるまで待つ
    await expect(
      page.locator(`.drive-filename:has-text("grid-test-${uid}")`).first(),
    ).toBeVisible({ timeout: 10_000 });

    const items = page.locator(".drive-item");
    const count = await items.count();
    expect(count).toBeGreaterThanOrEqual(4);

    // 各アイテムのバウンディングボックスを取得して重なりをチェック
    const boxes: { x: number; y: number; width: number; height: number }[] = [];
    for (let i = 0; i < count; i++) {
      const box = await items.nth(i).boundingBox();
      if (box) boxes.push(box);
    }

    // 任意の2つのアイテムが重なっていないことを確認
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i];
        const b = boxes[j];
        const overlapX = a.x < b.x + b.width && a.x + a.width > b.x;
        const overlapY = a.y < b.y + b.height && a.y + a.height > b.y;
        const overlaps = overlapX && overlapY;
        expect(overlaps, `drive-item ${i} and ${j} should not overlap`).toBeFalsy();
      }
    }
  });

  test("drive picker modal: images do not overlap in grid", async ({ page }) => {
    await loginAsAdmin(page);

    // 4枚の画像をアップロード
    const uid = Date.now();
    for (let i = 0; i < 4; i++) {
      const resp = await page.request.post("/api/v1/media", {
        multipart: {
          file: { name: `picker-test-${uid}-${i}.png`, mimeType: "image/png", buffer: png1x1() },
        },
      });
      expect(resp.ok()).toBeTruthy();
    }

    // タイムラインに移動してコンポーザーを開く
    await page.goto("/");
    await page.waitForSelector(".note-composer", { timeout: 10_000 });

    // ドライブボタン（フォルダアイコン — 2番目の .composer-attach-btn）をクリック
    const attachBtns = page.locator(".composer-attach-btn");
    // 最初のボタンはファイル添付、2番目がドライブ
    await attachBtns.nth(1).click();

    // DrivePicker モーダルが開く
    await page.waitForSelector(".drive-picker-grid", { timeout: 10_000 });

    const items = page.locator(".drive-picker-item");
    const count = await items.count();
    expect(count).toBeGreaterThanOrEqual(4);

    // 各アイテムのバウンディングボックスを取得して重なりをチェック
    const boxes: { x: number; y: number; width: number; height: number }[] = [];
    for (let i = 0; i < count; i++) {
      const box = await items.nth(i).boundingBox();
      if (box) boxes.push(box);
    }

    // 任意の2つのアイテムが重なっていないことを確認
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i];
        const b = boxes[j];
        const overlapX = a.x < b.x + b.width && a.x + a.width > b.x;
        const overlapY = a.y < b.y + b.height && a.y + a.height > b.y;
        const overlaps = overlapX && overlapY;
        expect(overlaps, `drive-picker-item ${i} and ${j} should not overlap`).toBeFalsy();
      }
    }
  });

  test("drive page: grid items have consistent size", async ({ page }) => {
    await loginAsAdmin(page);

    const uid = Date.now();
    for (let i = 0; i < 3; i++) {
      const resp = await page.request.post("/api/v1/media", {
        multipart: {
          file: { name: `size-test-${uid}-${i}.png`, mimeType: "image/png", buffer: png1x1() },
        },
      });
      expect(resp.ok()).toBeTruthy();
    }

    await page.goto("/drive");
    await page.waitForSelector(".drive-grid", { timeout: 10_000 });

    await expect(
      page.locator(`.drive-filename:has-text("size-test-${uid}")`).first(),
    ).toBeVisible({ timeout: 10_000 });

    const items = page.locator(".drive-item");
    const count = await items.count();
    expect(count).toBeGreaterThanOrEqual(3);

    // サムネイルの幅が同じ行内で一致していることを確認
    const widths: number[] = [];
    for (let i = 0; i < Math.min(count, 6); i++) {
      const box = await items.nth(i).boundingBox();
      if (box) widths.push(Math.round(box.width));
    }

    // 同じ行のアイテムは同じ幅であるべき（±2pxの誤差許容）
    const firstWidth = widths[0];
    for (const w of widths) {
      expect(Math.abs(w - firstWidth)).toBeLessThanOrEqual(2);
    }
  });
});
