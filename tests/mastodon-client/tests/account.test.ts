import { describe, it, expect, beforeAll } from "vitest";
import { getAccessToken, waitForHealth, authedFetch, BASE_URL } from "../src/setup";
import { assertAccount, assertDateTimeZ } from "../src/validators";

describe("Account API", () => {
  let token: string;

  beforeAll(async () => {
    await waitForHealth();
    ({ token } = await getAccessToken("accttest", "testpassword123"));
  });

  it("verify_credentials returns valid Account", async () => {
    const raw = await authedFetch("/api/v1/accounts/verify_credentials", token);
    assertAccount(raw, "verifyCredentials");
  });

  it("verify_credentials has CredentialAccount fields", async () => {
    const raw = await authedFetch("/api/v1/accounts/verify_credentials", token);
    // CredentialAccount extends Account with source
    if (raw.source) {
      if (raw.source.privacy) {
        const validPrivacy = ["public", "unlisted", "private", "direct"];
        if (!validPrivacy.includes(raw.source.privacy)) {
          throw new Error(`source.privacy invalid: ${raw.source.privacy}`);
        }
      }
    }
  });

  it("get account by ID returns valid Account", async () => {
    const me = await authedFetch("/api/v1/accounts/verify_credentials", token);
    const account = await authedFetch(`/api/v1/accounts/${me.id}`, token);
    assertAccount(account, "getAccount");
  });

  it("display_name is string, not null", async () => {
    const raw = await authedFetch("/api/v1/accounts/verify_credentials", token);
    assertAccount(raw);
  });

  it("created_at has Z suffix", async () => {
    const raw = await authedFetch("/api/v1/accounts/verify_credentials", token);
    assertDateTimeZ(raw.created_at, "account.created_at");
  });
});
