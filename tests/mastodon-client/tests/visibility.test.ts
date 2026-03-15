import { describe, it, expect, beforeAll } from "vitest";
import { getAccessToken, waitForHealth, createStatus } from "../src/setup";

describe("Visibility mapping", () => {
  let token: string;

  beforeAll(async () => {
    await waitForHealth();
    ({ token } = await getAccessToken("vistest", "testpassword123"));
  });

  it("public visibility is returned as 'public'", async () => {
    const status = await createStatus(token, {
      status: "Public post",
      visibility: "public",
    });
    expect(status.visibility).toBe("public");
  });

  it("unlisted visibility is returned as 'unlisted'", async () => {
    const status = await createStatus(token, {
      status: "Unlisted post",
      visibility: "unlisted",
    });
    expect(status.visibility).toBe("unlisted");
  });

  it("private visibility is returned as 'private' (not 'followers')", async () => {
    const status = await createStatus(token, {
      status: "Private post",
      visibility: "private",
    });
    expect(status.visibility).toBe("private");
  });

  it("direct visibility is returned as 'direct'", async () => {
    const status = await createStatus(token, {
      status: "Direct post",
      visibility: "direct",
    });
    expect(status.visibility).toBe("direct");
  });
});
