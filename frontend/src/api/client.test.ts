import { describe, it, expect, beforeEach, vi } from "vitest";
import { apiRequest } from "./client";

describe("apiRequest", () => {
  const mockFetch = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch);
    mockFetch.mockReset();
  });

  it("makes a GET request by default", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ data: "test" }),
    });
    const result = await apiRequest("/api/test");
    expect(result).toEqual({ data: "test" });
    expect(mockFetch).toHaveBeenCalledWith("/api/test", expect.objectContaining({
      method: "GET",
      credentials: "include",
    }));
  });

  it("sets Content-Type to application/json for non-formData requests", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
    });
    await apiRequest("/api/test");
    const [, config] = mockFetch.mock.calls[0];
    expect(config.headers["Content-Type"]).toBe("application/json");
  });

  it("sends JSON body for POST requests", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ id: "1" }),
    });
    const body = { content: "hello" };
    await apiRequest("/api/test", { method: "POST", body });
    const [, config] = mockFetch.mock.calls[0];
    expect(config.method).toBe("POST");
    expect(config.body).toBe(JSON.stringify(body));
  });

  it("sends FormData without Content-Type header", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ id: "1" }),
    });
    const formData = new FormData();
    formData.append("file", "data");
    await apiRequest("/api/upload", { method: "POST", formData });
    const [, config] = mockFetch.mock.calls[0];
    expect(config.body).toBe(formData);
    expect(config.headers["Content-Type"]).toBeUndefined();
  });

  it("throws error with detail message on failure", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 422,
      json: () => Promise.resolve({ detail: "Validation error" }),
    });
    await expect(apiRequest("/api/test")).rejects.toThrow("Validation error");
  });

  it("throws error with error field on failure", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 500,
      json: () => Promise.resolve({ error: "Server error" }),
    });
    await expect(apiRequest("/api/test")).rejects.toThrow("Server error");
  });

  it("throws Unknown error fallback when json parse fails", async () => {
    // When response.json() fails, catch returns { error: "Unknown error" }
    mockFetch.mockResolvedValue({
      ok: false,
      status: 403,
      json: () => Promise.reject(new Error("parse error")),
    });
    await expect(apiRequest("/api/test")).rejects.toThrow("Unknown error");
  });

  it("includes credentials in all requests", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
    });
    await apiRequest("/api/test");
    const [, config] = mockFetch.mock.calls[0];
    expect(config.credentials).toBe("include");
  });

  it("merges custom headers", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
    });
    await apiRequest("/api/test", {
      headers: { "X-Custom": "value" },
    });
    const [, config] = mockFetch.mock.calls[0];
    expect(config.headers["X-Custom"]).toBe("value");
    expect(config.headers["Content-Type"]).toBe("application/json");
  });

  it("supports DELETE method", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
    });
    await apiRequest("/api/test/1", { method: "DELETE" });
    const [, config] = mockFetch.mock.calls[0];
    expect(config.method).toBe("DELETE");
  });
});
