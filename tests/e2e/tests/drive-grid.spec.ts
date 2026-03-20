import { test, expect, type Page } from "@playwright/test";
import { loginAsAdmin, png1x1, pngOfSize } from "./helpers";

/**
 * ドライブのグリッドレイアウトが様々なサイズの画像で正しく動作し、
 * 画像の重なり合いが発生しないことを検証する。
 */

/** 各種サイズのテスト画像パターン */
const IMAGE_PATTERNS = [
  { name: "tiny", w: 16, h: 16 },
  { name: "square", w: 200, h: 200 },
  { name: "wide", w: 800, h: 200 },
  { name: "tall", w: 200, h: 800 },
  { name: "large", w: 1280, h: 960 },
  { name: "hd", w: 1920, h: 1080 },
] as const;

/** アップロード済み画像のIDを返す */
async function uploadTestImages(page: Page, prefix: string) {
  const ids: string[] = [];
  for (const pat of IMAGE_PATTERNS) {
    const buf = pngOfSize(pat.w, pat.h);
    const resp = await page.request.post("/api/v1/media", {
      multipart: {
        file: {
          name: `${prefix}-${pat.name}-${pat.w}x${pat.h}.png`,
          mimeType: "image/png",
          buffer: buf,
        },
      },
    });
    expect(resp.ok(), `upload ${pat.name} ${pat.w}x${pat.h}`).toBeTruthy();
    const data = await resp.json();
    ids.push(data.id);
  }
  return ids;
}

/** バウンディングボックス同士が重なっているかチェック */
function hasOverlap(
  boxes: { x: number; y: number; width: number; height: number }[],
): { i: number; j: number } | null {
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i];
      const b = boxes[j];
      // 1px の誤差を許容
      const overlapX = a.x < b.x + b.width - 1 && a.x + a.width - 1 > b.x;
      const overlapY = a.y < b.y + b.height - 1 && a.y + a.height - 1 > b.y;
      if (overlapX && overlapY) return { i, j };
    }
  }
  return null;
}

test.describe("Drive grid layout — various image sizes", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("drive page: different sized images do not overlap", async ({
    page,
  }) => {
    const uid = Date.now();
    await uploadTestImages(page, `drv-${uid}`);

    await page.goto("/drive");
    await page.waitForSelector(".drive-grid", { timeout: 10_000 });
    await expect(
      page.locator(`.drive-filename:has-text("drv-${uid}")`).first(),
    ).toBeVisible({ timeout: 10_000 });

    const items = page.locator(".drive-item");
    const count = await items.count();
    expect(count).toBeGreaterThanOrEqual(IMAGE_PATTERNS.length);

    const boxes: { x: number; y: number; width: number; height: number }[] = [];
    for (let i = 0; i < count; i++) {
      const box = await items.nth(i).boundingBox();
      if (box) boxes.push(box);
    }

    const overlap = hasOverlap(boxes);
    expect(overlap, `drive items should not overlap`).toBeNull();
  });

  test("drive picker: different sized images do not overlap", async ({
    page,
  }) => {
    const uid = Date.now();
    await uploadTestImages(page, `pick-${uid}`);

    await page.goto("/");
    await page.waitForSelector(".note-composer", { timeout: 10_000 });
    const attachBtns = page.locator(".composer-attach-btn");
    await attachBtns.nth(1).click();
    await page.waitForSelector(".drive-picker-grid", { timeout: 10_000 });

    const items = page.locator(".drive-picker-item");
    const count = await items.count();
    expect(count).toBeGreaterThanOrEqual(IMAGE_PATTERNS.length);

    const boxes: { x: number; y: number; width: number; height: number }[] = [];
    for (let i = 0; i < count; i++) {
      const box = await items.nth(i).boundingBox();
      if (box) boxes.push(box);
    }

    const overlap = hasOverlap(boxes);
    expect(overlap, `drive-picker items should not overlap`).toBeNull();
  });

  test("drive picker: items have consistent size regardless of image dimensions", async ({
    page,
  }) => {
    const uid = Date.now();
    await uploadTestImages(page, `sz-${uid}`);

    await page.goto("/");
    await page.waitForSelector(".note-composer", { timeout: 10_000 });
    const attachBtns = page.locator(".composer-attach-btn");
    await attachBtns.nth(1).click();
    await page.waitForSelector(".drive-picker-grid", { timeout: 10_000 });

    const items = page.locator(".drive-picker-item");
    const count = await items.count();
    expect(count).toBeGreaterThanOrEqual(IMAGE_PATTERNS.length);

    // 先頭6つの幅と高さを取得
    const sizes: { w: number; h: number }[] = [];
    for (let i = 0; i < Math.min(count, 6); i++) {
      const box = await items.nth(i).boundingBox();
      if (box) sizes.push({ w: Math.round(box.width), h: Math.round(box.height) });
    }

    // 正方形であること（border分の誤差 ±6px 許容）
    for (const s of sizes) {
      expect(
        Math.abs(s.w - s.h),
        `item should be square: ${s.w}x${s.h}`,
      ).toBeLessThanOrEqual(6);
    }

    // 同じ行のアイテムは同じ幅（±2px）
    const firstWidth = sizes[0].w;
    for (const s of sizes) {
      expect(
        Math.abs(s.w - firstWidth),
        `item width ${s.w} should match first ${firstWidth}`,
      ).toBeLessThanOrEqual(2);
    }
  });

  test("drive picker mobile (375px): grid fits within viewport", async ({
    page,
  }) => {
    const uid = Date.now();
    await uploadTestImages(page, `mob-${uid}`);

    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto("/");
    await page.waitForSelector(".note-composer", { timeout: 10_000 });
    const attachBtns = page.locator(".composer-attach-btn");
    await attachBtns.nth(1).click();
    await page.waitForSelector(".drive-picker-grid", { timeout: 10_000 });

    const items = page.locator(".drive-picker-item");
    const count = await items.count();
    expect(count).toBeGreaterThanOrEqual(IMAGE_PATTERNS.length);

    // グリッド全体がビューポート内に収まっている
    const gridBox = await page.locator(".drive-picker-grid").boundingBox();
    expect(gridBox).not.toBeNull();
    expect(gridBox!.x).toBeGreaterThanOrEqual(0);
    expect(gridBox!.x + gridBox!.width).toBeLessThanOrEqual(375 + 1);

    // 各アイテムがビューポート幅を超えていない
    const boxes: { x: number; y: number; width: number; height: number }[] = [];
    for (let i = 0; i < count; i++) {
      const box = await items.nth(i).boundingBox();
      if (box) {
        expect(
          box.x + box.width,
          `item ${i} should not exceed viewport width`,
        ).toBeLessThanOrEqual(375 + 1);
        boxes.push(box);
      }
    }

    // アイテム同士が重ならない
    const overlap = hasOverlap(boxes);
    expect(overlap, `mobile drive-picker items should not overlap`).toBeNull();
  });

  test("drive page mobile (375px): grid fits within viewport", async ({
    page,
  }) => {
    const uid = Date.now();
    await uploadTestImages(page, `dmob-${uid}`);

    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto("/drive");
    await page.waitForSelector(".drive-grid", { timeout: 10_000 });
    await expect(
      page.locator(`.drive-filename:has-text("dmob-${uid}")`).first(),
    ).toBeVisible({ timeout: 10_000 });

    const items = page.locator(".drive-item");
    const count = await items.count();
    expect(count).toBeGreaterThanOrEqual(IMAGE_PATTERNS.length);

    const boxes: { x: number; y: number; width: number; height: number }[] = [];
    for (let i = 0; i < count; i++) {
      const box = await items.nth(i).boundingBox();
      if (box) {
        expect(
          box.x + box.width,
          `drive-item ${i} should not exceed viewport width`,
        ).toBeLessThanOrEqual(375 + 1);
        boxes.push(box);
      }
    }

    const overlap = hasOverlap(boxes);
    expect(overlap, `mobile drive items should not overlap`).toBeNull();
  });
});
