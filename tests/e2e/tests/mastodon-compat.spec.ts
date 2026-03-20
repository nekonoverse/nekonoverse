import { test, expect } from "@playwright/test";
import { loginAsAdmin, registerAndLogin } from "./helpers";

test.describe("Mastodon Compatibility API", { tag: "@serial" }, () => {
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  // --- favourite / unfavourite ---

  test("favourite and unfavourite a status", async ({ page }) => {
    // Create a status
    const createResp = await page.request.post("/api/v1/statuses", {
      data: { content: "fav e2e test", visibility: "public" },
    });
    expect(createResp.ok()).toBeTruthy();
    const note = await createResp.json();
    const noteId = note.id;

    // Favourite
    const favResp = await page.request.post(
      `/api/v1/statuses/${noteId}/favourite`,
    );
    expect(favResp.ok()).toBeTruthy();
    const favBody = await favResp.json();
    expect(favBody.favourited).toBe(true);

    // Unfavourite
    const unfavResp = await page.request.post(
      `/api/v1/statuses/${noteId}/unfavourite`,
    );
    expect(unfavResp.ok()).toBeTruthy();
    const unfavBody = await unfavResp.json();
    expect(unfavBody.favourited).toBe(false);
  });

  test("favourite is idempotent", async ({ page }) => {
    const createResp = await page.request.post("/api/v1/statuses", {
      data: { content: "fav idempotent", visibility: "public" },
    });
    const noteId = (await createResp.json()).id;

    await page.request.post(`/api/v1/statuses/${noteId}/favourite`);
    const resp = await page.request.post(
      `/api/v1/statuses/${noteId}/favourite`,
    );
    expect(resp.ok()).toBeTruthy();
    expect((await resp.json()).favourited).toBe(true);
  });

  // --- favourited_by ---

  test("favourited_by returns accounts", async ({ page }) => {
    const createResp = await page.request.post("/api/v1/statuses", {
      data: { content: "fav by e2e", visibility: "public" },
    });
    const noteId = (await createResp.json()).id;

    await page.request.post(`/api/v1/statuses/${noteId}/favourite`);

    const resp = await page.request.get(
      `/api/v1/statuses/${noteId}/favourited_by`,
    );
    expect(resp.ok()).toBeTruthy();
    const accounts = await resp.json();
    expect(accounts.length).toBeGreaterThanOrEqual(1);
    expect(accounts[0].username).toBeDefined();
  });

  test("favourited_by returns empty when no favourites", async ({ page }) => {
    const createResp = await page.request.post("/api/v1/statuses", {
      data: { content: "no fav e2e", visibility: "public" },
    });
    const noteId = (await createResp.json()).id;

    const resp = await page.request.get(
      `/api/v1/statuses/${noteId}/favourited_by`,
    );
    expect(resp.ok()).toBeTruthy();
    expect(await resp.json()).toEqual([]);
  });

  // --- accounts/relationships ---

  test("relationships returns batch results", async ({ page, browser }) => {
    const baseURL = process.env.E2E_BASE_URL || "http://localhost:3080";
    const uid = Date.now();

    // Register another user
    const userSession = await registerAndLogin(
      browser,
      `rel_user_${uid}`,
      "testpassword123",
      baseURL,
    );

    // Get the new user's account ID
    const verifyResp = await userSession.page.request.get(
      "/api/v1/accounts/verify_credentials",
    );
    const otherAccount = await verifyResp.json();

    // Check relationships
    const resp = await page.request.get(
      `/api/v1/accounts/relationships?id[]=${otherAccount.id}`,
    );
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body.length).toBe(1);
    expect(body[0].id).toBe(otherAccount.id);
    expect(typeof body[0].following).toBe("boolean");
    expect(typeof body[0].followed_by).toBe("boolean");
    expect(typeof body[0].blocking).toBe("boolean");
    expect(typeof body[0].muting).toBe("boolean");

    await userSession.context.close();
  });

  test("relationships with no ids returns empty", async ({ page }) => {
    const resp = await page.request.get("/api/v1/accounts/relationships");
    expect(resp.ok()).toBeTruthy();
    expect(await resp.json()).toEqual([]);
  });

  // --- search ---

  test("search accounts by username", async ({ page }) => {
    const resp = await page.request.get(
      "/api/v2/search?q=admin&type=accounts",
    );
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body.accounts.length).toBeGreaterThanOrEqual(1);
    expect(body.statuses).toEqual([]);
    expect(body.hashtags).toEqual([]);
  });

  test("search statuses by content", async ({ page }) => {
    const unique = `e2esearch_${Date.now()}`;
    await page.request.post("/api/v1/statuses", {
      data: { content: unique, visibility: "public" },
    });

    const resp = await page.request.get(
      `/api/v2/search?q=${unique}&type=statuses`,
    );
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body.statuses.length).toBeGreaterThanOrEqual(1);
    expect(body.accounts).toEqual([]);
    expect(body.hashtags).toEqual([]);
  });

  test("search hashtags", async ({ page }) => {
    const tag = `e2etag${Date.now()}`;
    await page.request.post("/api/v1/statuses", {
      data: { content: `post with #${tag}`, visibility: "public" },
    });

    const resp = await page.request.get(
      `/api/v2/search?q=${tag}&type=hashtags`,
    );
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body.hashtags.length).toBeGreaterThanOrEqual(1);
    expect(body.hashtags[0].name).toBe(tag);
  });

  test("search all types", async ({ page }) => {
    const resp = await page.request.get("/api/v2/search?q=test");
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body).toHaveProperty("accounts");
    expect(body).toHaveProperty("statuses");
    expect(body).toHaveProperty("hashtags");
  });
});
