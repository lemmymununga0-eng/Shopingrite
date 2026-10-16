import { beforeEach, describe, expect, it, vi } from "vitest";

const session = vi.hoisted(() => ({ token: "tok-abc" }));
vi.mock("../services/supabase", () => ({
  supabase: { auth: { getSession: async () => ({ data: { session: session.token ? { access_token: session.token } : null } }) } },
}));

import { api, setUnauthorizedHandler } from "../services/api";

const reply = (status, body) => vi.fn().mockResolvedValue({ status, ok: status < 400, json: async () => body });
beforeEach(() => { session.token = "tok-abc"; setUnauthorizedHandler(() => {}); });

describe("api client", () => {
  it("sends the Supabase access token as a Bearer header", async () => {
    globalThis.fetch = reply(200, { items: [] });
    await api.transactions({ page: 2, search: "", risk: "High" });
    const [url, opts] = globalThis.fetch.mock.calls[0];
    expect(opts.headers.Authorization).toBe("Bearer tok-abc");
    expect(url).toContain("/transactions?page=2&risk=High");      // empty params are dropped
  });
  it("omits the header when signed out", async () => {
    session.token = null;
    globalThis.fetch = reply(200, {});
    await api.health();
    expect(globalThis.fetch.mock.calls[0][1].headers).not.toHaveProperty("Authorization");
  });
  it("signs the user out and throws on 401", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    globalThis.fetch = reply(401, { detail: "Invalid or missing authentication token" });
    await expect(api.stats()).rejects.toThrow(/session has expired/i);
    expect(handler).toHaveBeenCalled();
  });
  it("turns field-level validation errors into a readable message", async () => {
    globalThis.fetch = reply(422, { detail: "Validation failed", errors: [{ field: "hour", message: "less than or equal to 23" }] });
    await expect(api.predict({})).rejects.toThrow("hour: less than or equal to 23");
  });
  it("reports 503 details from the server", async () => {
    globalThis.fetch = reply(503, { detail: "Model unavailable: Model file not found" });
    await expect(api.predict({})).rejects.toThrow(/model unavailable/i);
  });
  it("explains when the API cannot be reached", async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(api.health()).rejects.toThrow(/cannot reach/i);
  });
  it("PATCHes alert reviews with status and notes", async () => {
    globalThis.fetch = reply(200, {});
    await api.reviewAlert("abc", "false_positive", "ok");
    const [url, opts] = globalThis.fetch.mock.calls[0];
    expect(opts.method).toBe("PATCH");
    expect(url).toMatch(/\/alerts\/abc$/);
    expect(JSON.parse(opts.body)).toEqual({ status: "false_positive", notes: "ok" });
  });
});
