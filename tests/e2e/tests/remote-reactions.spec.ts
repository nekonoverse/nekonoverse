import { test, expect } from "@playwright/test";
import {
  loginAsAdmin,
  createNote,
  registerAndLogin,
  getActorId,
} from "./helpers";

test.describe("Remote reaction display", () => {
  test("reaction from another user appears on note card", async ({
    page,
    browser,
  }) => {
    // admin がノートを作成
    await loginAsAdmin(page);
    const uid = Date.now();
    const note = await createNote(page, `remote-react-${uid}`);

    // 別ユーザー (reactor) を作成してリアクションを付ける
    const baseURL =
      process.env.E2E_BASE_URL ?? "http://localhost:3080";
    const { page: reactorPage, context: reactorCtx } =
      await registerAndLogin(browser, `reactor${uid}`, "Reactor1234!", baseURL);

    // 👍 を使用 — ⭐はReactionBarから除外され専用ボタンに移動したため
    const reactResp = await reactorPage.request.post(
      `/api/v1/statuses/${note.id}/react/%F0%9F%91%8D`,
    );
    expect(reactResp.ok()).toBeTruthy();
    await reactorCtx.close();

    // admin のタイムラインでリアクションバッジが表示されるか確認
    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const noteCard = page
      .locator(".note-card")
      .filter({ hasText: `remote-react-${uid}` })
      .first();

    // リアクションバッジ (👍 1) が表示される
    const badge = noteCard.locator(".reaction-badge");
    await expect(badge).toBeVisible({ timeout: 5_000 });
    await expect(badge).toContainText("1");
  });

  test("reaction badge does not have reaction-me class for other user's reaction", async ({
    page,
    browser,
  }) => {
    await loginAsAdmin(page);
    const uid = Date.now();
    const note = await createNote(page, `not-my-react-${uid}`);

    const baseURL =
      process.env.E2E_BASE_URL ?? "http://localhost:3080";
    const { page: reactorPage, context: reactorCtx } =
      await registerAndLogin(
        browser,
        `other${uid}`,
        "Other1234!",
        baseURL,
      );

    await reactorPage.request.post(
      `/api/v1/statuses/${note.id}/react/%F0%9F%91%8D`,
    );
    await reactorCtx.close();

    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const noteCard = page
      .locator(".note-card")
      .filter({ hasText: `not-my-react-${uid}` })
      .first();

    const badge = noteCard.locator(".reaction-badge").first();
    await expect(badge).toBeVisible({ timeout: 5_000 });

    // 他人のリアクションなので reaction-me は付かない
    await expect(badge).not.toHaveClass(/reaction-me/);
  });

  test("multiple reactions from different users show correct count", async ({
    page,
    browser,
  }) => {
    await loginAsAdmin(page);
    const uid = Date.now();
    const note = await createNote(page, `multi-react-${uid}`);

    const baseURL =
      process.env.E2E_BASE_URL ?? "http://localhost:3080";

    // 2人のユーザーが同じ絵文字でリアクション
    for (const name of [`userA${uid}`, `userB${uid}`]) {
      const { page: p, context: c } = await registerAndLogin(
        browser,
        name,
        "Pass1234!",
        baseURL,
      );
      await p.request.post(
        `/api/v1/statuses/${note.id}/react/%F0%9F%8E%89`,
      );
      await c.close();
    }

    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const noteCard = page
      .locator(".note-card")
      .filter({ hasText: `multi-react-${uid}` })
      .first();

    const badge = noteCard.locator(".reaction-badge").first();
    await expect(badge).toBeVisible({ timeout: 5_000 });
    await expect(badge).toContainText("2");
  });

  test("different emoji reactions show separate badges", async ({
    page,
    browser,
  }) => {
    await loginAsAdmin(page);
    const uid = Date.now();
    const note = await createNote(page, `diff-emoji-${uid}`);

    const baseURL =
      process.env.E2E_BASE_URL ?? "http://localhost:3080";

    // ユーザーA: 👍 (⭐はReactionBarから除外されたため)
    const { page: pA, context: cA } = await registerAndLogin(
      browser,
      `emojiA${uid}`,
      "Pass1234!",
      baseURL,
    );
    await pA.request.post(
      `/api/v1/statuses/${note.id}/react/%F0%9F%91%8D`,
    );
    await cA.close();

    // ユーザーB: 🎉
    const { page: pB, context: cB } = await registerAndLogin(
      browser,
      `emojiB${uid}`,
      "Pass1234!",
      baseURL,
    );
    await pB.request.post(
      `/api/v1/statuses/${note.id}/react/%F0%9F%8E%89`,
    );
    await cB.close();

    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const noteCard = page
      .locator(".note-card")
      .filter({ hasText: `diff-emoji-${uid}` })
      .first();

    // 2つの別々のバッジが表示される
    const badges = noteCard.locator(".reaction-badge");
    await expect(badges).toHaveCount(2, { timeout: 5_000 });
  });

  test("reaction appears via SSE push without page reload", async ({
    page,
    browser,
  }) => {
    await loginAsAdmin(page);
    const uid = Date.now();
    const note = await createNote(page, `sse-react-${uid}`);

    // タイムラインを表示して SSE 接続を確立
    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const noteCard = page
      .locator(".note-card")
      .filter({ hasText: `sse-react-${uid}` })
      .first();

    // まだリアクションバッジがないことを確認
    await expect(noteCard.locator(".reaction-badge")).toHaveCount(0);

    // 別ユーザーがリアクションを付ける（ページリロードしない）
    const baseURL =
      process.env.E2E_BASE_URL ?? "http://localhost:3080";
    const { page: reactorPage, context: reactorCtx } =
      await registerAndLogin(
        browser,
        `sse${uid}`,
        "SSEtest1!",
        baseURL,
      );
    // 👍 を使用 — ⭐はReactionBarから除外されたため
    await reactorPage.request.post(
      `/api/v1/statuses/${note.id}/react/%F0%9F%91%8D`,
    );
    await reactorCtx.close();

    // SSE プッシュでリアクションバッジが自動表示されるのを待つ
    const badge = noteCard.locator(".reaction-badge");
    await expect(badge).toBeVisible({ timeout: 10_000 });
    await expect(badge).toContainText("1");
  });

  test("hover on reaction badge shows reacted-by popover", async ({
    page,
    browser,
  }) => {
    await loginAsAdmin(page);
    const uid = Date.now();
    const note = await createNote(page, `longpress-${uid}`);

    const baseURL =
      process.env.E2E_BASE_URL ?? "http://localhost:3080";
    const { page: reactorPage, context: reactorCtx } =
      await registerAndLogin(
        browser,
        `lp${uid}`,
        "LongPress1!",
        baseURL,
      );
    await reactorPage.request.post(
      `/api/v1/statuses/${note.id}/react/%E2%9D%A4`,
    );
    await reactorCtx.close();

    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const noteCard = page
      .locator(".note-card")
      .filter({ hasText: `longpress-${uid}` })
      .first();

    const badge = noteCard.locator(".reaction-badge").first();
    await expect(badge).toBeVisible({ timeout: 5_000 });

    // ホバーでポップオーバーが表示される (PCモード)
    await badge.hover();

    const popover = page.locator(".action-popover");
    await expect(popover).toBeVisible({ timeout: 5_000 });

    // リアクションしたユーザーが表示される
    const item = popover.locator(".reacted-by-item").first();
    await expect(item).toBeVisible({ timeout: 5_000 });
    await expect(item.locator(".reacted-by-handle")).toContainText(
      `@lp${uid}`,
    );
  });
});
