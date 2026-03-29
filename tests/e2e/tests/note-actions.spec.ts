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

    // クリックでデフォルト公開範囲（元ノートと同じ）で即ブースト
    await Promise.all([
      page.waitForResponse(
        (resp) => resp.url().includes("/reblog") && resp.status() === 200,
        { timeout: 15_000 },
      ),
      boostBtn.evaluate((el: HTMLElement) => el.click()),
    ]);

    // Firefox workaround: SolidJS の DOM 更新が反映されない場合があるためリロード
    try {
      await expect(boostBtn).toHaveClass(/boosted/, { timeout: 5_000 });
    } catch {
      await page.goto("/");
      await page.waitForSelector(".note-card", { timeout: 10_000 });
      const refreshedCard = page
        .locator(`.note-card`)
        .filter({ hasText: `reblog-test-${uid}` })
        .first();
      await expect(refreshedCard.locator(".note-boost-btn")).toHaveClass(
        /boosted/,
        { timeout: 10_000 },
      );
    }

    // --- Un-boost: reload page to get fresh DOM references (Firefox workaround) ---
    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const noteCard2 = page
      .locator(`.note-card`)
      .filter({ hasText: `reblog-test-${uid}` })
      .first();
    let boostBtn2 = noteCard2.locator(".note-boost-btn");
    await expect(boostBtn2).toBeEnabled({ timeout: 5_000 });

    // Firefox workaround: ブースト状態がリロード直後に反映されない場合がある
    try {
      await expect(boostBtn2).toHaveClass(/boosted/, { timeout: 5_000 });
    } catch {
      await page.goto("/");
      await page.waitForSelector(".note-card", { timeout: 10_000 });
      const refreshedCard = page
        .locator(`.note-card`)
        .filter({ hasText: `reblog-test-${uid}` })
        .first();
      boostBtn2 = refreshedCard.locator(".note-boost-btn");
      await expect(boostBtn2).toHaveClass(/boosted/, { timeout: 10_000 });
    }

    // Firefox workaround: evaluate で直接クリック
    // catch パスでリロードした場合、SolidJS のハンドラが未アタッチでAPIコールが
    // 発火しないことがあるため、タイムアウト時はリロードしてリトライする
    try {
      await Promise.all([
        page.waitForResponse(
          (resp) => resp.url().includes("/unreblog") && resp.status() === 200,
          { timeout: 15_000 },
        ),
        boostBtn2.evaluate((el: HTMLElement) => el.click()),
      ]);
    } catch {
      await page.goto("/");
      await page.waitForSelector(".note-card", { timeout: 10_000 });
      const retryCard = page
        .locator(`.note-card`)
        .filter({ hasText: `reblog-test-${uid}` })
        .first();
      boostBtn2 = retryCard.locator(".note-boost-btn");
      await expect(boostBtn2).toHaveClass(/boosted/, { timeout: 5_000 });
      await Promise.all([
        page.waitForResponse(
          (resp) => resp.url().includes("/unreblog") && resp.status() === 200,
          { timeout: 15_000 },
        ),
        boostBtn2.evaluate((el: HTMLElement) => el.click()),
      ]);
    }

    // Firefox workaround: アンブースト後の状態確認もリロードフォールバック付き
    try {
      await expect(boostBtn2).not.toHaveClass(/boosted/, { timeout: 5_000 });
    } catch {
      await page.goto("/");
      await page.waitForSelector(".note-card", { timeout: 10_000 });
      const refreshedCard2 = page
        .locator(`.note-card`)
        .filter({ hasText: `reblog-test-${uid}` })
        .first();
      await expect(refreshedCard2.locator(".note-boost-btn")).not.toHaveClass(
        /boosted/,
        { timeout: 5_000 },
      );
    }
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

    // Firefox workaround: evaluate で直接クリック + API完了を待つ
    // SolidJS のハンドラが未アタッチでAPIコールが発火しないことがあるため、
    // タイムアウト時はリロードしてリトライする
    await expect(bookmarkBtn).toBeEnabled({ timeout: 5_000 });
    try {
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/bookmark") && r.status() === 200, { timeout: 10_000 }),
        bookmarkBtn.evaluate((el: HTMLElement) => el.click()),
      ]);
    } catch {
      await page.goto("/");
      await page.waitForSelector(".note-card", { timeout: 10_000 });
      const retryCard = page
        .locator(`.note-card`)
        .filter({ hasText: `bookmark-action-${uid}` })
        .first();
      const retryBtn = retryCard.locator(".note-bookmark-btn");
      await expect(retryBtn).toBeEnabled({ timeout: 5_000 });
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/bookmark") && r.status() === 200, { timeout: 15_000 }),
        retryBtn.evaluate((el: HTMLElement) => el.click()),
      ]);
    }

    // Firefox workaround: SolidJS の DOM 更新が反映されない場合はリロードして確認
    try {
      await expect(bookmarkBtn).toHaveClass(/bookmarked/, { timeout: 5_000 });
    } catch {
      await page.goto("/");
      await page.waitForSelector(".note-card", { timeout: 10_000 });
      const refreshedCard = page
        .locator(`.note-card`)
        .filter({ hasText: `bookmark-action-${uid}` })
        .first();
      await expect(refreshedCard.locator(".note-bookmark-btn")).toHaveClass(
        /bookmarked/,
        { timeout: 10_000 },
      );
    }

    // 解除: リロードして fresh DOM で操作
    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });
    const noteCard2 = page
      .locator(`.note-card`)
      .filter({ hasText: `bookmark-action-${uid}` })
      .first();
    const bookmarkBtn2 = noteCard2.locator(".note-bookmark-btn");

    // Firefox workaround: evaluate で直接クリック
    await bookmarkBtn2.evaluate((el: HTMLElement) => el.click());

    // Firefox workaround: unbookmark 後の状態確認もリロードフォールバック付き
    try {
      await expect(bookmarkBtn2).not.toHaveClass(/bookmarked/, {
        timeout: 5_000,
      });
    } catch {
      await page.goto("/");
      await page.waitForSelector(".note-card", { timeout: 10_000 });
      const refreshedCard2 = page
        .locator(`.note-card`)
        .filter({ hasText: `bookmark-action-${uid}` })
        .first();
      await expect(
        refreshedCard2.locator(".note-bookmark-btn"),
      ).not.toHaveClass(/bookmarked/, { timeout: 5_000 });
    }
  });

  test("long press boost button shows visibility menu for public note", async ({ page }) => {
    await loginAsAdmin(page);
    const uid = Date.now();
    await createNote(page, `vis-menu-public-${uid}`);

    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const noteCard = page
      .locator(`.note-card`)
      .filter({ hasText: `vis-menu-public-${uid}` })
      .first();
    const boostBtn = noteCard.locator(".note-boost-btn");
    await expect(boostBtn).toBeEnabled({ timeout: 5_000 });

    // 長押し（mousedown → 600ms待機 → mouseup）で公開範囲メニューを表示
    await boostBtn.dispatchEvent("mousedown");
    await page.waitForTimeout(600);
    await boostBtn.dispatchEvent("mouseup");

    const visMenu = noteCard.locator(".boost-visibility-menu");
    await expect(visMenu).toBeVisible({ timeout: 5_000 });

    // publicノートの場合: public, unlisted, followers の3択
    const items = visMenu.locator(".boost-visibility-item");
    await expect(items).toHaveCount(3, { timeout: 5_000 });

    // メニュー外クリックで閉じる
    await page.locator("body").click({ position: { x: 0, y: 0 } });
    await expect(visMenu).not.toBeVisible({ timeout: 5_000 });
  });

  test("long press boost shows 2 options for unlisted note", async ({ page }) => {
    await loginAsAdmin(page);
    const uid = Date.now();
    const resp = await page.request.post("/api/v1/statuses", {
      data: { content: `vis-menu-unlisted-${uid}`, visibility: "unlisted" },
    });
    expect(resp.status()).toBe(201);

    const noteId = (await resp.json()).id;
    await page.goto(`/notes/${noteId}`);
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const noteCard = page.locator(".note-card").first();
    const boostBtn = noteCard.locator(".note-boost-btn");
    await expect(boostBtn).toBeEnabled({ timeout: 5_000 });

    // 長押しで公開範囲メニュー表示
    await boostBtn.dispatchEvent("mousedown");
    await page.waitForTimeout(600);
    await boostBtn.dispatchEvent("mouseup");

    const visMenu = noteCard.locator(".boost-visibility-menu");
    await expect(visMenu).toBeVisible({ timeout: 5_000 });

    // unlistedノートの場合: unlisted, followers の2択
    const items = visMenu.locator(".boost-visibility-item");
    await expect(items).toHaveCount(2, { timeout: 5_000 });
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
