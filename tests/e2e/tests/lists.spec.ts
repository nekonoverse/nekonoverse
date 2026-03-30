import { test, expect } from "@playwright/test";
import { loginAsAdmin, registerAndLogin, createNote, getActorId } from "./helpers";

test.describe("Lists", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("create a list via UI", async ({ page }) => {
    await page.goto("/lists");
    await expect(page.locator(".page-container")).toBeVisible({ timeout: 10_000 });

    const uid = Date.now();
    const listName = `E2E List ${uid}`;
    await page.locator(".list-form input[type='text']").fill(listName);
    await page.locator(".list-form button[type='submit']").click();

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

    // メタ情報(リスト名)が表示されること
    await expect(page.locator(".list-tl-meta")).toBeVisible({ timeout: 10_000 });
  });

  test("add and remove a member from a list", async ({ browser, page }) => {
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

    // リストタイムラインページでメンバーパネルを確認
    await page.goto(`/lists/${list.id}`);
    await expect(page.locator(".list-tl-header")).toBeVisible({ timeout: 10_000 });

    // メンバー一覧にユーザーが表示されること
    await expect(async () => {
      const membersPanel = page.locator(".list-members-panel");
      await expect(membersPanel).toBeVisible({ timeout: 5_000 });
      const memberRows = membersPanel.locator(".list-member-row");
      const count = await memberRows.count();
      expect(count).toBeGreaterThanOrEqual(1);
    }).toPass({ timeout: 15_000 });

    // メンバーを削除
    const removeResp = await page.request.delete(`/api/v1/lists/${list.id}/accounts`, {
      data: { account_ids: [memberActorId] },
    });
    expect(removeResp.status()).toBe(200);

    // API経由で削除されたことを確認
    const tlResp = await page.request.get(`/api/v1/lists/${list.id}`);
    expect(tlResp.status()).toBe(200);

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
    // (リストメンバーはフォロー中のユーザーである必要がある場合に備える)
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

    // UIでもリストタイムラインに表示されること
    await page.goto(`/lists/${list.id}`);
    await expect(page.locator(".list-tl-header")).toBeVisible({ timeout: 10_000 });

    await memberSession.context.close();
  });
});
