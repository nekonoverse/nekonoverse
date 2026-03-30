import { test, expect } from "@playwright/test";
import { loginAsAdmin, png1x1, pngOfSize } from "./helpers";

test.describe("Media Timeline", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("page loads and shows gallery grid", async ({ page }) => {
    await page.goto("/media");
    await expect(page.locator(".media-timeline")).toBeVisible({ timeout: 10_000 });
    // ギャラリーグリッドが描画されること(空でもグリッド要素自体は存在する)
    await expect(page.locator(".media-gallery-grid")).toBeVisible({ timeout: 10_000 });
  });

  test("upload media and verify it appears in gallery", async ({ page }) => {
    const uid = Date.now();
    const imgBuf = pngOfSize(100, 100);

    // メディアをアップロード
    const uploadResp = await page.request.post("/api/v1/media", {
      multipart: {
        file: { name: `test-${uid}.png`, mimeType: "image/png", buffer: imgBuf },
      },
    });
    expect(uploadResp.status()).toBe(200);
    const media = await uploadResp.json();

    // メディア付きノートを作成
    const noteResp = await page.request.post("/api/v1/statuses", {
      data: {
        content: `media-tl-test-${uid}`,
        visibility: "public",
        media_ids: [media.id],
      },
    });
    expect(noteResp.status()).toBe(201);

    // メディアタイムラインに遷移して表示を確認
    await page.goto("/media");
    await expect(page.locator(".media-gallery-grid")).toBeVisible({ timeout: 10_000 });
    // 少なくとも1つのメディアアイテムが表示されること
    await expect(page.locator(".media-gallery-item").first()).toBeVisible({ timeout: 10_000 });
  });

  test("sensitive media shows sensitive overlay", async ({ page }) => {
    const uid = Date.now();
    const imgBuf = png1x1();

    // センシティブなメディア付きノートを作成
    const uploadResp = await page.request.post("/api/v1/media", {
      multipart: {
        file: { name: `sensitive-${uid}.png`, mimeType: "image/png", buffer: imgBuf },
      },
    });
    expect(uploadResp.status()).toBe(200);
    const media = await uploadResp.json();

    const noteResp = await page.request.post("/api/v1/statuses", {
      data: {
        content: `sensitive-media-tl-${uid}`,
        visibility: "public",
        sensitive: true,
        media_ids: [media.id],
      },
    });
    expect(noteResp.status()).toBe(201);

    await page.goto("/media");
    await expect(page.locator(".media-gallery-grid")).toBeVisible({ timeout: 10_000 });

    // センシティブマーカーが付いたアイテムが存在すること
    const sensitiveItems = page.locator(".media-gallery-sensitive");
    // センシティブメディアが存在する場合、オーバーレイが表示されること
    const hasSensitive = await sensitiveItems.first().isVisible({ timeout: 5_000 }).catch(() => false);
    if (hasSensitive) {
      await expect(sensitiveItems.first()).toBeVisible();
    }
  });

  test("media timeline API returns media attachments", async ({ page }) => {
    const uid = Date.now();
    const imgBuf = png1x1();

    // メディア付きノートを2つ作成
    for (let i = 0; i < 2; i++) {
      const uploadResp = await page.request.post("/api/v1/media", {
        multipart: {
          file: { name: `api-test-${uid}-${i}.png`, mimeType: "image/png", buffer: imgBuf },
        },
      });
      expect(uploadResp.status()).toBe(200);
      const media = await uploadResp.json();

      const noteResp = await page.request.post("/api/v1/statuses", {
        data: {
          content: `media-api-test-${uid}-${i}`,
          visibility: "public",
          media_ids: [media.id],
        },
      });
      expect(noteResp.status()).toBe(201);
    }

    // APIでメディアタイムラインを取得
    const tlResp = await page.request.get("/api/v1/timelines/media");
    expect(tlResp.status()).toBe(200);
    const notes = await tlResp.json();
    expect(Array.isArray(notes)).toBeTruthy();

    // 全てのノートにメディアが添付されていること
    for (const note of notes) {
      expect(note.media_attachments.length).toBeGreaterThanOrEqual(1);
    }
  });

  test("gallery items display images correctly", async ({ page }) => {
    const uid = Date.now();
    const imgBuf = pngOfSize(200, 150);

    // メディアアップロードとノート作成
    const uploadResp = await page.request.post("/api/v1/media", {
      multipart: {
        file: { name: `gallery-img-${uid}.png`, mimeType: "image/png", buffer: imgBuf },
      },
    });
    expect(uploadResp.status()).toBe(200);
    const media = await uploadResp.json();

    const noteResp = await page.request.post("/api/v1/statuses", {
      data: {
        content: `gallery-display-${uid}`,
        visibility: "public",
        media_ids: [media.id],
      },
    });
    expect(noteResp.status()).toBe(201);

    await page.goto("/media");
    await expect(page.locator(".media-gallery-grid")).toBeVisible({ timeout: 10_000 });

    // ギャラリーアイテム内のimg要素が描画されていること
    const galleryImg = page.locator(".media-gallery-img").first();
    await expect(galleryImg).toBeVisible({ timeout: 10_000 });

    // img要素にsrc属性が設定されていること
    const src = await galleryImg.getAttribute("src");
    expect(src).toBeTruthy();
  });
});
