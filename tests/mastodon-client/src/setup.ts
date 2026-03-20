import { createRestAPIClient, type mastodon } from "masto";

const BASE_URL = process.env.TEST_SERVER_URL || "http://localhost:3080";

export { BASE_URL };

/**
 * Wait for the instance to be healthy.
 */
export async function waitForHealth(timeout = 60_000): Promise<void> {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    try {
      const resp = await fetch(`${BASE_URL}/api/v1/health`);
      if (resp.ok) return;
    } catch {
      // retry
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`Instance not healthy after ${timeout}ms`);
}

/**
 * Register a user, create an OAuth app, and return an authenticated masto.js client.
 * Also returns the raw access token for making direct fetch calls.
 */
export async function createAuthenticatedClient(
  username: string,
  password: string,
): Promise<mastodon.rest.Client> {
  const { token } = await getAccessToken(username, password);
  return createRestAPIClient({
    url: BASE_URL,
    accessToken: token,
  });
}

/**
 * Register a user and get an access token (for raw fetch calls).
 */
export async function getAccessToken(
  username: string,
  password: string,
): Promise<{ token: string }> {
  const email = `${username}@example.com`;

  // Step 1: Register user (POST /api/v1/accounts)
  const regResp = await fetch(`${BASE_URL}/api/v1/accounts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, email, password }),
  });
  if (!regResp.ok && regResp.status !== 409 && regResp.status !== 422) {
    throw new Error(`Registration failed: ${regResp.status} ${await regResp.text()}`);
  }

  // Step 2: Create OAuth app
  const appResp = await fetch(`${BASE_URL}/api/v1/apps`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      client_name: `test-${username}`,
      redirect_uris: "urn:ietf:wg:oauth:2.0:oob",
      scopes: "read write follow push",
    }),
  });
  if (!appResp.ok) {
    throw new Error(`App creation failed: ${appResp.status} ${await appResp.text()}`);
  }
  const app = await appResp.json();

  // Step 3: Get authorization code
  const authResp = await fetch(`${BASE_URL}/oauth/authorize`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: app.client_id,
      redirect_uri: "urn:ietf:wg:oauth:2.0:oob",
      scope: "read write follow push",
      response_type: "code",
      username,
      password,
    }),
    redirect: "manual",
  });

  // Extract code from Location header or response body
  let code: string;
  const location = authResp.headers.get("location");
  if (location) {
    const url = new URL(location, BASE_URL);
    code = url.searchParams.get("code")!;
  } else {
    const body = await authResp.text();
    const match = body.match(/code=([^&"<\s]+)/);
    if (!match) {
      throw new Error(`Could not extract auth code. Status: ${authResp.status}, Body: ${body.slice(0, 500)}`);
    }
    code = match[1];
  }

  // Step 4: Exchange code for token
  const tokenResp = await fetch(`${BASE_URL}/oauth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code,
      client_id: app.client_id,
      client_secret: app.client_secret,
      redirect_uri: "urn:ietf:wg:oauth:2.0:oob",
    }),
  });
  if (!tokenResp.ok) {
    throw new Error(`Token exchange failed: ${tokenResp.status} ${await tokenResp.text()}`);
  }
  const tokenData = await tokenResp.json();

  return { token: tokenData.access_token };
}

/**
 * Authenticated raw JSON fetch.
 */
export async function authedFetch(
  path: string,
  token: string,
  options?: RequestInit,
): Promise<any> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    ...((options?.headers as Record<string, string>) || {}),
  };
  const resp = await fetch(`${BASE_URL}${path}`, { ...options, headers });
  if (!resp.ok) {
    throw new Error(`${path} failed: ${resp.status} ${await resp.text()}`);
  }
  return resp.json();
}

/**
 * Create a status via raw API call (returns raw JSON, not masto.js transformed).
 */
export async function createStatus(
  token: string,
  params: { status: string; visibility?: string; spoiler_text?: string; in_reply_to_id?: string },
): Promise<any> {
  return authedFetch("/api/v1/statuses", token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
}
