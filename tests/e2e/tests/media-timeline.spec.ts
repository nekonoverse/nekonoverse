import { test, expect } from "@playwright/test";
import { loginAsAdmin, png1x1, pngOfSize } from "./helpers";

test.describe("Media Timeline", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("page loads and shows gallery grid", async ({ page }) => {
    await page.goto("/media-timeline");
    await expect(page.locator(".media-timeline")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(".media-gallery-grid")).toBeVisible({ timeout: 10_000 });
  });

  test("upload media and verify it appears in gallery", async ({ page }) => {
    const uid = Date.now();
    const imgBuf = pngOfSize(100, 100);

    const uploadResp = await page.request.post("/api/v1/media", {
      multipart: {
        file: { name: `test-${uid}.png`, mimeType: "image/png", buffer: imgBuf },
      },
    });
    expect(uploadResp.status()).toBe(200);
    const media = await uploadResp.json();

    const noteResp = await page.request.post("/api/v1/statuses", {
      data: {
        content: `media-tl-test-${uid}`,
        visibility: "public",
        media_ids: [media.id],
      },
    });
    expect(noteResp.status()).toBe(201);

    await page.goto("/media-timeline");
    await expect(page.locator(".media-gallery-grid")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(".media-gallery-item").first()).toBeVisible({ timeout: 10_000 });
  });

  test("media timeline API returns only notes with attachments", async ({ page }) => {
    const uid = Date.now();
    const imgBuf = png1x1();

    // メディア付きノートを作成
    const uploadResp = await page.request.post("/api/v1/media", {
      multipart: {
        file: { name: `api-test-${uid}.png`, mimeType: "image/png", buffer: imgBuf },
      },
    });
    expect(uploadResp.status()).toBe(200);
    const media = await uploadResp.json();

    const noteResp = await page.request.post("/api/v1/statuses", {
      data: {
        content: `media-api-test-${uid}`,
        visibility: "public",
        media_ids: [media.id],
      },
    });
    expect(noteResp.status()).toBe(201);

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

    await page.goto("/media-timeline");
    await expect(page.locator(".media-gallery-grid")).toBeVisible({ timeout: 10_000 });

    const galleryImg = page.locator(".media-gallery-img").first();
    await expect(galleryImg).toBeVisible({ timeout: 10_000 });

    const src = await galleryImg.getAttribute("src");
    expect(src).toBeTruthy();
  });
});
