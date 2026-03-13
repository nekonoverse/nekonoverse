import { test, expect } from "@playwright/test";
import { loginAsAdmin, registerAndLogin } from "./helpers";

test.describe("Push Subscription API", { tag: "@serial" }, () => {
  test.describe.configure({ mode: "serial" });

  const dummySubscription = {
    subscription: {
      endpoint: "https://push.example.com/send/abc123",
      keys: {
        p256dh:
          "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8p8REfWPU",
        auth: "tBHItJI5svbpC7_Sqh_Abg",
      },
    },
  };

  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("create push subscription", async ({ page }) => {
    const resp = await page.request.post("/api/v1/push/subscription", {
      data: dummySubscription,
    });
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();

    expect(body.id).toBeDefined();
    expect(body.endpoint).toBe(dummySubscription.subscription.endpoint);
    expect(body.server_key).toBeDefined();
    expect(body.server_key.length).toBeGreaterThan(40);

    // Default alerts
    expect(body.alerts.mention).toBe(true);
    expect(body.alerts.follow).toBe(true);
    expect(body.alerts.favourite).toBe(true);
    expect(body.alerts.reblog).toBe(true);
    expect(body.alerts.poll).toBe(true);
    expect(body.policy).toBe("all");
  });

  test("get push subscription", async ({ page }) => {
    // Create first
    const createResp = await page.request.post("/api/v1/push/subscription", {
      data: dummySubscription,
    });
    expect(createResp.ok()).toBeTruthy();

    // Get
    const getResp = await page.request.get("/api/v1/push/subscription");
    expect(getResp.ok()).toBeTruthy();
    const body = await getResp.json();

    expect(body.endpoint).toBe(dummySubscription.subscription.endpoint);
    expect(body.server_key).toBeDefined();
  });

  test("update push subscription alerts", async ({ page }) => {
    // Create first
    await page.request.post("/api/v1/push/subscription", {
      data: dummySubscription,
    });

    // Update alerts
    const updateResp = await page.request.put("/api/v1/push/subscription", {
      data: {
        data: {
          alerts: {
            mention: true,
            follow: false,
            favourite: false,
          },
          policy: "followed",
        },
      },
    });
    expect(updateResp.ok()).toBeTruthy();
    const body = await updateResp.json();

    expect(body.alerts.mention).toBe(true);
    expect(body.alerts.follow).toBe(false);
    expect(body.alerts.favourite).toBe(false);
    // Untouched alerts should retain default values
    expect(body.alerts.reblog).toBe(true);
    expect(body.alerts.poll).toBe(true);
    expect(body.policy).toBe("followed");
  });

  test("delete push subscription", async ({ page }) => {
    // Create first
    await page.request.post("/api/v1/push/subscription", {
      data: dummySubscription,
    });

    // Delete
    const deleteResp = await page.request.delete(
      "/api/v1/push/subscription",
    );
    expect(deleteResp.ok()).toBeTruthy();

    // Get should return 404
    const getResp = await page.request.get("/api/v1/push/subscription");
    expect(getResp.status()).toBe(404);
  });

  test("get subscription returns 404 when none exists", async ({ page }) => {
    // Ensure no subscription (delete if exists)
    await page.request.delete("/api/v1/push/subscription");

    const resp = await page.request.get("/api/v1/push/subscription");
    expect(resp.status()).toBe(404);
  });

  test("update subscription returns 404 when none exists", async ({
    page,
  }) => {
    // Ensure no subscription
    await page.request.delete("/api/v1/push/subscription");

    const resp = await page.request.put("/api/v1/push/subscription", {
      data: {
        data: { alerts: { mention: false } },
      },
    });
    expect(resp.status()).toBe(404);
  });

  test("delete subscription returns 404 when none exists", async ({
    page,
  }) => {
    // Ensure no subscription
    await page.request.delete("/api/v1/push/subscription");

    const resp = await page.request.delete("/api/v1/push/subscription");
    expect(resp.status()).toBe(404);
  });

  test("create subscription with custom alerts", async ({ page }) => {
    const resp = await page.request.post("/api/v1/push/subscription", {
      data: {
        ...dummySubscription,
        data: {
          alerts: {
            mention: true,
            follow: false,
            favourite: true,
            reblog: false,
            poll: false,
          },
          policy: "follower",
        },
      },
    });
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();

    expect(body.alerts.mention).toBe(true);
    expect(body.alerts.follow).toBe(false);
    expect(body.alerts.favourite).toBe(true);
    expect(body.alerts.reblog).toBe(false);
    expect(body.alerts.poll).toBe(false);
    expect(body.policy).toBe("follower");
  });

  test("creating subscription replaces existing one", async ({ page }) => {
    // Create first subscription
    const resp1 = await page.request.post("/api/v1/push/subscription", {
      data: {
        subscription: {
          endpoint: "https://push.example.com/old",
          keys: dummySubscription.subscription.keys,
        },
      },
    });
    expect(resp1.ok()).toBeTruthy();

    // Create second subscription (should replace)
    const resp2 = await page.request.post("/api/v1/push/subscription", {
      data: {
        subscription: {
          endpoint: "https://push.example.com/new",
          keys: dummySubscription.subscription.keys,
        },
      },
    });
    expect(resp2.ok()).toBeTruthy();

    // Get should return the new one
    const getResp = await page.request.get("/api/v1/push/subscription");
    expect(getResp.ok()).toBeTruthy();
    const body = await getResp.json();
    expect(body.endpoint).toBe("https://push.example.com/new");
  });

  test("push subscription requires authentication", async ({ browser }) => {
    const baseURL = process.env.E2E_BASE_URL || "http://localhost:3080";
    const context = await browser.newContext({ baseURL });
    const unauthPage = await context.newPage();

    const resp = await unauthPage.request.post("/api/v1/push/subscription", {
      data: dummySubscription,
    });
    // Should fail (401)
    expect(resp.status()).toBeGreaterThanOrEqual(400);

    await context.close();
  });

  test("subscriptions are per-session (different users)", async ({
    browser,
    page,
  }) => {
    const baseURL = process.env.E2E_BASE_URL || "http://localhost:3080";
    const uid = Date.now();

    // Create subscription for admin
    const adminCreateResp = await page.request.post(
      "/api/v1/push/subscription",
      {
        data: {
          subscription: {
            endpoint: "https://push.example.com/admin-endpoint",
            keys: dummySubscription.subscription.keys,
          },
        },
      },
    );
    expect(adminCreateResp.ok()).toBeTruthy();

    // Register another user
    const userSession = await registerAndLogin(
      browser,
      `push_user_${uid}`,
      "testpassword123",
      baseURL,
    );

    // New user should not have a subscription
    const userGetResp = await userSession.page.request.get(
      "/api/v1/push/subscription",
    );
    expect(userGetResp.status()).toBe(404);

    // New user creates their own subscription
    const userCreateResp = await userSession.page.request.post(
      "/api/v1/push/subscription",
      {
        data: {
          subscription: {
            endpoint: "https://push.example.com/user-endpoint",
            keys: dummySubscription.subscription.keys,
          },
        },
      },
    );
    expect(userCreateResp.ok()).toBeTruthy();

    // Admin's subscription should still be their own
    const adminGetResp = await page.request.get(
      "/api/v1/push/subscription",
    );
    expect(adminGetResp.ok()).toBeTruthy();
    const adminSub = await adminGetResp.json();
    expect(adminSub.endpoint).toBe(
      "https://push.example.com/admin-endpoint",
    );

    await userSession.context.close();
  });
});
