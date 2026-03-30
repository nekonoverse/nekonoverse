import { test, expect } from "@playwright/test";
import { loginAsAdmin, registerAndLogin, createNote, getActorId } from "./helpers";

test.describe("Lists", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("create a list via UI", async ({ page }) => {
    await page.goto("/lists");
    await expect(page.locator(".page-container")).toBeVisible({ timeout: 10_000 });

    // 「作成」ボタンをクリックしてフォームを表示
    await page.locator(".lists-header .btn-primary").click();
    await expect(page.locator(".list-form")).toBeVisible({ timeout: 5_000 });

    const uid = Date.now();
    const listName = `E2E List ${uid}`;
    await page.locator(".list-form input.input").fill(listName);
    // フォーム内の「作成」ボタンをクリック
    await page.locator(".list-form-actions .btn-primary").click();

    // リスト一覧に作成したリストが表示されること
    await expect(
      page.locator(".list-card-title").filter({ hasText: listName }),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("create and delete a list via API", async ({ page }) => {
    const uid = Date.now();

    // API経由でリスト作成
    const createResp = await page.request.post("/api/v1/lists", {
      data: { title: `Delete Test ${uid}` },
    });
    expect(createResp.status()).toBe(200);
    const list = await createResp.json();

    // 削除
    const deleteResp = await page.request.delete(`/api/v1/lists/${list.id}`);
    expect(deleteResp.status()).toBe(200);

    // 削除後にリスト一覧から消えていること
    const listResp = await page.request.get("/api/v1/lists");
    const lists = await listResp.json();
    const found = lists.find((l: any) => l.id === list.id);
    expect(found).toBeUndefined();
  });

  test("rename a list via API and verify on UI", async ({ page }) => {
    const uid = Date.now();

    const createResp = await page.request.post("/api/v1/lists", {
      data: { title: `Rename Before ${uid}` },
    });
    expect(createResp.status()).toBe(200);
    const list = await createResp.json();

    // リネーム
    const newTitle = `Renamed List ${uid}`;
    const updateResp = await page.request.put(`/api/v1/lists/${list.id}`, {
      data: { title: newTitle },
    });
    expect(updateResp.status()).toBe(200);
    const updated = await updateResp.json();
    expect(updated.title).toBe(newTitle);

    // UIで確認
    await page.goto("/lists");
    await expect(page.locator(".page-container")).toBeVisible({ timeout: 10_000 });
    await expect(
      page.locator(".list-card-title").filter({ hasText: newTitle }),
    ).toBeVisible({ timeout: 10_000 });

    // 旧名が表示されていないこと
    await expect(
      page.locator(".list-card-title").filter({ hasText: `Rename Before ${uid}` }),
    ).toHaveCount(0);
  });

  test("view list timeline page", async ({ page }) => {
    const uid = Date.now();

    const createResp = await page.request.post("/api/v1/lists", {
      data: { title: `Timeline Test ${uid}` },
    });
    expect(createResp.status()).toBe(200);
    const list = await createResp.json();

    // リストタイムラインページに遷移
    await page.goto(`/lists/${list.id}`);
    await expect(page.locator(".list-tl-header")).toBeVisible({ timeout: 10_000 });
  });

  test("add and remove a member via API", async ({ browser, page }) => {
    const baseURL = process.env.E2E_BASE_URL || "http://localhost:3080";
    const uid = Date.now();
    const memberName = `list_member_${uid}`;

    // メンバー用ユーザーを作成
    const memberSession = await registerAndLogin(
      browser,
      memberName,
      "testpassword123",
      baseURL,
    );

    // リスト作成
    const createResp = await page.request.post("/api/v1/lists", {
      data: { title: `Members Test ${uid}` },
    });
    expect(createResp.status()).toBe(200);
    const list = await createResp.json();

    // メンバーのactor_idを取得してリストに追加
    const memberActorId = await getActorId(page, memberName);
    const addResp = await page.request.post(`/api/v1/lists/${list.id}/accounts`, {
      data: { account_ids: [memberActorId] },
    });
    expect(addResp.status()).toBe(200);

    // APIでメンバーが追加されたことを確認
    const accountsResp = await page.request.get(`/api/v1/lists/${list.id}/accounts`);
    expect(accountsResp.status()).toBe(200);
    const accounts = await accountsResp.json();
    const found = accounts.find((a: any) => a.id === memberActorId);
    expect(found).toBeTruthy();

    // メンバーを削除
    const removeResp = await page.request.delete(`/api/v1/lists/${list.id}/accounts`, {
      data: { account_ids: [memberActorId] },
    });
    expect(removeResp.status()).toBe(200);

    // 削除後にメンバーが消えていること
    const accountsAfter = await page.request.get(`/api/v1/lists/${list.id}/accounts`);
    const afterList = await accountsAfter.json();
    const notFound = afterList.find((a: any) => a.id === memberActorId);
    expect(notFound).toBeUndefined();

    await memberSession.context.close();
  });

  test("list with replies_policy option", async ({ page }) => {
    const uid = Date.now();

    // replies_policyを指定してリスト作成
    const createResp = await page.request.post("/api/v1/lists", {
      data: { title: `Policy Test ${uid}`, replies_policy: "followed" },
    });
    expect(createResp.status()).toBe(200);
    const list = await createResp.json();
    expect(list.replies_policy).toBe("followed");

    // 取得して確認
    const getResp = await page.request.get(`/api/v1/lists/${list.id}`);
    expect(getResp.status()).toBe(200);
    const fetched = await getResp.json();
    expect(fetched.title).toBe(`Policy Test ${uid}`);
    expect(fetched.replies_policy).toBe("followed");
  });

  test("list timeline shows notes from members", async ({ browser, page }) => {
    const baseURL = process.env.E2E_BASE_URL || "http://localhost:3080";
    const uid = Date.now();
    const memberName = `list_tl_user_${uid}`;

    // メンバー用ユーザー作成・ログイン
    const memberSession = await registerAndLogin(
      browser,
      memberName,
      "testpassword123",
      baseURL,
    );

    // admin側: メンバーをフォローしてからリストに追加
    const memberActorId = await getActorId(page, memberName);
    await page.request.post(`/api/v1/accounts/${memberActorId}/follow`);

    // リスト作成
    const createResp = await page.request.post("/api/v1/lists", {
      data: { title: `TL Notes Test ${uid}` },
    });
    expect(createResp.status()).toBe(200);
    const list = await createResp.json();

    // メンバー追加
    const addResp = await page.request.post(`/api/v1/lists/${list.id}/accounts`, {
      data: { account_ids: [memberActorId] },
    });
    expect(addResp.status()).toBe(200);

    // メンバーがノートを投稿
    const noteText = `list-tl-note-${uid}`;
    await createNote(memberSession.page, noteText);

    // リストタイムラインAPIでノートが取得できること
    await expect(async () => {
      const tlResp = await page.request.get(`/api/v1/timelines/list/${list.id}`);
      expect(tlResp.status()).toBe(200);
      const notes = await tlResp.json();
      const found = notes.find((n: any) => n.content?.includes(noteText));
      expect(found).toBeTruthy();
    }).toPass({ timeout: 15_000 });

    await memberSession.context.close();
  });
});
